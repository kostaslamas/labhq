"""Subscribing needs a passkey session; the endpoints store and remove what the browser sends."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from labhq.api.app import create_app
from labhq.api.deps import ResolverRegistry
from labhq.api.routes import RouterRegistry, health_router
from labhq.api.settings import ApiSettings
from labhq.auth.resolver import resolve_session
from labhq.auth.routes import public_router
from labhq.auth.routes import router as auth_router
from labhq.cli.context import Context
from labhq.db.models import PushSubscription
from labhq.notify.routes import router as push_router
from tests.auth.conftest import LOCAL, WRITE, auth_env, context, enrolled, settings, signed_in

__all__ = ["auth_env", "context", "enrolled", "settings", "signed_in"]

ENDPOINT = "https://push.example.test/send/abc"
BODY = {"endpoint": ENDPOINT, "keys": {"p256dh": "BPublicKey", "auth": "secret"}}


@pytest.fixture
def app_client(context: Context, tmp_path: Path) -> Iterator[TestClient]:
    """The auth fixtures' client, with the push router registered next to the auth ones."""
    resolvers = ResolverRegistry()
    resolvers.register("web-session", resolve_session)
    routers = RouterRegistry()
    routers.register(health_router, public=True)
    routers.register(public_router, public=True)
    routers.register(auth_router)
    routers.register(push_router)
    app = create_app(
        context,
        routers=routers,
        resolvers=resolvers,
        settings=ApiSettings(ui_dir=tmp_path / "no-ui"),
    )
    with TestClient(app, base_url=LOCAL, headers={"Origin": LOCAL}) as client:
        yield client


async def stored(context: Context) -> list[str]:
    async with context.sessions() as db:
        return list(await db.scalars(select(PushSubscription.endpoint)))


async def test_subscribing_without_a_passkey_session_is_refused(
    app_client: TestClient, context: Context
) -> None:
    for path in ("/api/push/subscriptions", "/api/push/subscriptions/remove"):
        response = app_client.post(path, json=BODY, headers=WRITE)
        assert response.status_code == 401, path
        assert response.json()["error"]["code"] == "unauthorized"
    assert app_client.get("/api/push/status").status_code == 401
    assert await stored(context) == []


async def test_a_signed_in_browser_subscribes_and_unsubscribes(
    signed_in: TestClient, context: Context
) -> None:
    assert signed_in.post("/api/push/subscriptions", json=BODY, headers=WRITE).status_code == 204
    assert await stored(context) == [ENDPOINT]

    # The same browser subscribing again replaces its keys rather than adding a second row.
    renewed = {**BODY, "keys": {"p256dh": "BNewKey", "auth": "newer"}}
    assert signed_in.post("/api/push/subscriptions", json=renewed, headers=WRITE).status_code == 204
    async with context.sessions() as db:
        (row,) = await db.scalars(select(PushSubscription))
    assert (row.p256dh, row.auth) == ("BNewKey", "newer")

    remove = {"endpoint": ENDPOINT}
    response = signed_in.post("/api/push/subscriptions/remove", json=remove, headers=WRITE)
    assert response.status_code == 204
    assert await stored(context) == []


async def test_only_https_endpoints_are_accepted(signed_in: TestClient, context: Context) -> None:
    body = {**BODY, "endpoint": "http://push.example.test/send/abc"}
    response = signed_in.post("/api/push/subscriptions", json=body, headers=WRITE)
    assert response.status_code == 422
    assert await stored(context) == []


async def test_status_gives_the_public_key_and_never_the_private_one(
    signed_in: TestClient, context: Context
) -> None:
    status = signed_in.get("/api/push/status").json()
    assert status["active"] is True
    assert status["public_key"].startswith("B")  # An uncompressed P-256 point.
    pem = (context.settings.data_dir / "vapid_private.pem").read_text()
    assert pem not in str(status)
    assert signed_in.get("/api/push/status").json() == status
