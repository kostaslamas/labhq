from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from labhq.api.app import create_app
from labhq.api.deps import ResolverRegistry
from labhq.api.routes import RouterRegistry, health_router
from labhq.api.settings import ApiSettings
from labhq.auth import enrollment
from labhq.auth.resolver import resolve_session
from labhq.auth.routes import public_router, router
from labhq.auth.settings import AuthSettings, get_auth_settings
from labhq.cli.context import Context
from labhq.clock import FakeClock
from labhq.db import create_engine, session_factory
from labhq.settings import Settings
from tests.auth.authenticator import SoftwareAuthenticator

LOCAL = "http://localhost:8787"
PUBLIC = "https://labhq.example.org"
WRITE = {"X-Labhq-Request": "1"}


@pytest.fixture(autouse=True)
def auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LABHQ_PUBLIC_URL", PUBLIC)


@pytest.fixture
async def context(database_url: str, tmp_path: Path, clock: FakeClock) -> AsyncIterator[Context]:
    engine = create_engine(database_url)
    settings = Settings(data_dir=tmp_path / "data", database_url=database_url)
    try:
        yield Context(settings, session_factory(engine), clock)
    finally:
        await engine.dispose()


@pytest.fixture
def settings(auth_env: None) -> AuthSettings:
    return get_auth_settings()


@pytest.fixture
def app_client(context: Context, tmp_path: Path) -> Iterator[TestClient]:
    resolvers = ResolverRegistry()
    resolvers.register("web-session", resolve_session)
    routers = RouterRegistry()
    routers.register(health_router, public=True)
    routers.register(public_router, public=True)
    routers.register(router)
    app = create_app(
        context,
        routers=routers,
        resolvers=resolvers,
        settings=ApiSettings(ui_dir=tmp_path / "no-ui"),
    )
    with TestClient(app, base_url=LOCAL, headers={"Origin": LOCAL}) as client:
        yield client


async def link_token(context: Context, settings: AuthSettings, base: str = LOCAL) -> str:
    async with context.sessions() as db:
        link = await enrollment.create_link(db, settings, context.clock.now(), base)
        await db.commit()
    return link.url.split("#", 1)[1]


def enroll(
    client: TestClient, token: str, authenticator: SoftwareAuthenticator, origin: str = LOCAL
) -> Any:
    """Run both enrollment calls the way the page does; returns the final response."""
    headers = {"Origin": origin}
    options = client.post("/api/auth/enroll/options", json={"token": token}, headers=headers)
    assert options.status_code == 200, options.text
    credential = authenticator.create(options.json(), origin)
    return client.post(
        "/api/auth/enroll/verify",
        json={"token": token, "credential": credential, "name": "test key"},
        headers=headers,
    )


def log_in(client: TestClient, authenticator: SoftwareAuthenticator, origin: str = LOCAL) -> Any:
    headers = {"Origin": origin}
    options = client.post("/api/auth/login/options", headers=headers)
    assert options.status_code == 200, options.text
    assertion = authenticator.get(options.json(), origin)
    return client.post("/api/auth/login/verify", json={"credential": assertion}, headers=headers)


@pytest.fixture
async def enrolled(
    app_client: TestClient, context: Context, settings: AuthSettings
) -> SoftwareAuthenticator:
    authenticator = SoftwareAuthenticator()
    response = enroll(app_client, await link_token(context, settings), authenticator)
    assert response.status_code == 200, response.text
    return authenticator


@pytest.fixture
async def signed_in(app_client: TestClient, enrolled: SoftwareAuthenticator) -> TestClient:
    assert log_in(app_client, enrolled).status_code == 200
    return app_client
