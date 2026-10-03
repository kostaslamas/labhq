from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from fastapi import APIRouter, FastAPI
from starlette.testclient import TestClient

import labhq
from labhq.api import app as app_module
from labhq.api.app import create_app
from labhq.api.deps import ClockDep, OwnerDep, ResolverRegistry
from labhq.api.hooks import HookRegistry, LifespanHook
from labhq.api.routes import RouterRegistry, default_routers, health_router
from labhq.api.settings import ApiSettings
from labhq.cli.context import Context

from .conftest import OWNER_HEADER

APP_SOURCE = Path(app_module.__file__).read_bytes()


def dummy_router() -> APIRouter:
    router = APIRouter(prefix="/dummy", tags=["dummy"])

    @router.get("")
    async def dummy_get(owner: OwnerDep, clock: ClockDep) -> dict[str, str]:
        return {"owner": owner.subject, "now": clock.now().isoformat()}

    return router


def registries(*routers: APIRouter) -> RouterRegistry:
    registry = RouterRegistry()
    registry.register(health_router, public=True)
    for router in routers:
        registry.register(router)
    return registry


def test_health_needs_no_session_and_returns_the_version(api_settings: ApiSettings) -> None:
    with TestClient(create_app(settings=api_settings, resolvers=ResolverRegistry())) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"version": labhq.__version__}


def test_with_no_resolver_registered_a_route_is_401(
    context: Context, api_settings: ApiSettings
) -> None:
    app = create_app(
        context,
        routers=registries(dummy_router()),
        resolvers=ResolverRegistry(),
        settings=api_settings,
    )
    with TestClient(app) as client:
        response = client.get("/api/dummy", headers={OWNER_HEADER: "kostas"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    assert "www-authenticate" in response.headers


def test_a_router_without_an_owner_parameter_is_still_protected(api_settings: ApiSettings) -> None:
    router = APIRouter()

    @router.get("/open")
    async def open_get() -> dict[str, bool]:
        return {"open": True}

    app = create_app(
        routers=registries(router), resolvers=ResolverRegistry(), settings=api_settings
    )
    with TestClient(app) as client:
        assert client.get("/api/open").status_code == 401


def test_a_new_router_is_one_registration_and_app_py_is_untouched(
    context: Context, resolvers: ResolverRegistry, api_settings: ApiSettings
) -> None:
    app = create_app(
        context, routers=registries(dummy_router()), resolvers=resolvers, settings=api_settings
    )
    with TestClient(app) as client:
        response = client.get("/api/dummy", headers={OWNER_HEADER: "kostas"})
    assert response.status_code == 200
    assert response.json() == {
        "owner": "kostas",
        "now": context.clock.now().isoformat(),
    }
    assert Path(app_module.__file__).read_bytes() == APP_SOURCE


def test_a_startup_hook_is_one_registration_and_runs_around_the_app(
    api_settings: ApiSettings,
) -> None:
    events: list[str] = []
    hooks = HookRegistry()

    @asynccontextmanager
    async def broker(app: FastAPI) -> AsyncIterator[None]:
        events.append("start")
        app.state.broker = "ready"
        yield
        events.append("stop")

    hooks.register("broker", broker)
    app = create_app(hooks=hooks, resolvers=ResolverRegistry(), settings=api_settings)
    with TestClient(app):
        assert events == ["start"]
        assert app.state.broker == "ready"
    assert events == ["start", "stop"]
    assert Path(app_module.__file__).read_bytes() == APP_SOURCE


def test_hooks_stop_in_reverse_order(api_settings: ApiSettings) -> None:
    events: list[str] = []
    hooks = HookRegistry()

    def make(label: str) -> LifespanHook:
        @asynccontextmanager
        async def hook(app: FastAPI) -> AsyncIterator[None]:
            events.append(f"start {label}")
            yield
            events.append(f"stop {label}")

        return hook

    for name in ("first", "second"):
        hooks.register(name, make(name))
    with TestClient(create_app(hooks=hooks, resolvers=ResolverRegistry(), settings=api_settings)):
        pass
    assert events == ["start first", "start second", "stop second", "stop first"]


def test_registries_refuse_duplicates() -> None:
    with pytest.raises(ValueError):
        default_routers.register(health_router, public=True)
    resolvers = ResolverRegistry()
    resolvers.register("a", lambda request: None)  # type: ignore[arg-type,return-value]
    with pytest.raises(ValueError):
        resolvers.register("a", lambda request: None)  # type: ignore[arg-type,return-value]
