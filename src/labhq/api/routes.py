"""Router registry: each area adds its router here with one line.

Every registered router requires the owner unless registered `public=True`; a route is
protected by default and has to opt out, never opt in.
"""

from collections.abc import Iterator
from dataclasses import dataclass

from fastapi import APIRouter
from pydantic import BaseModel

import labhq
from labhq.api.approvals import router as approvals_router
from labhq.api.rules.routes import router as rules_router
from labhq.api.vocabulary import vocabulary_router
from labhq.auth.routes import public_router as auth_public_router
from labhq.auth.routes import router as auth_router
from labhq.live.endpoint import live_router


@dataclass(frozen=True)
class RouterSpec:
    router: APIRouter
    public: bool = False


class RouterRegistry:
    def __init__(self) -> None:
        self._specs: list[RouterSpec] = []

    def register(self, router: APIRouter, *, public: bool = False) -> None:
        if any(spec.router is router for spec in self._specs):
            raise ValueError("This router is already registered.")
        self._specs.append(RouterSpec(router, public))

    def __iter__(self) -> Iterator[RouterSpec]:
        return iter(self._specs)

    def __len__(self) -> int:
        return len(self._specs)


class Health(BaseModel):
    version: str


health_router = APIRouter(tags=["health"])


@health_router.get("/health")
async def health_get() -> Health:
    """Answer without a session, so a probe or the UI can tell the server is up."""
    return Health(version=labhq.__version__)


default_routers = RouterRegistry()
default_routers.register(health_router, public=True)
default_routers.register(vocabulary_router)
default_routers.register(live_router, public=True)  # Authenticates its own handshake.
default_routers.register(auth_public_router, public=True)  # Sign-in cannot need a session.
default_routers.register(auth_router)
default_routers.register(approvals_router)
default_routers.register(rules_router)
