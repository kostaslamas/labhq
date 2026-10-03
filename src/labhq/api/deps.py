"""Request dependencies: the program's context, a database session, the clock and the owner.

Authentication is a registry of session resolvers. Each one looks at the request and either
names the owner or passes. With none registered, nobody is the owner: secure by default.
"""

from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.api.errors import ApiError
from labhq.cli.context import Context
from labhq.clock import Clock

UNAUTHORIZED_CODE = "unauthorized"
UNAUTHORIZED_HEADERS = {"WWW-Authenticate": 'Session realm="labhq"'}


@dataclass(frozen=True)
class Owner:
    """The one person this labhq belongs to, as a resolver identified them."""

    subject: str


SessionResolver = Callable[[Request], Awaitable[Owner | None]]


class ResolverRegistry:
    def __init__(self) -> None:
        self._resolvers: dict[str, SessionResolver] = {}

    def register(self, name: str, resolver: SessionResolver) -> None:
        if name in self._resolvers:
            raise ValueError(f"Session resolver {name!r} is already registered.")
        self._resolvers[name] = resolver

    def __iter__(self) -> Iterator[SessionResolver]:
        return iter(self._resolvers.values())

    def __len__(self) -> int:
        return len(self._resolvers)


default_resolvers = ResolverRegistry()


def get_context(request: Request) -> Context:
    context: Context | None = request.app.state.context
    if context is None:
        raise ApiError(503, "no_context", "The API was started without a program context.")
    return context


ContextDep = Annotated[Context, Depends(get_context)]


async def get_session(context: ContextDep) -> AsyncIterator[AsyncSession]:
    async with context.sessions() as session:
        yield session


def get_clock(context: ContextDep) -> Clock:
    return context.clock


async def current_owner(request: Request) -> Owner:
    resolvers: ResolverRegistry = request.app.state.resolvers
    for resolve in resolvers:
        owner = await resolve(request)
        if owner is not None:
            return owner
    raise ApiError(401, UNAUTHORIZED_CODE, "Sign in to continue.", UNAUTHORIZED_HEADERS)


SessionDep = Annotated[AsyncSession, Depends(get_session)]
ClockDep = Annotated[Clock, Depends(get_clock)]
OwnerDep = Annotated[Owner, Depends(current_owner)]
