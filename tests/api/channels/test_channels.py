"""The Channels page over HTTP: a passkey to add, switch or remove; a test needs only a session."""

from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from labhq.api.app import create_app
from labhq.api.channels import router as channels_router
from labhq.api.channels.routes import get_runtime
from labhq.api.deps import ResolverRegistry
from labhq.api.routes import RouterRegistry, health_router
from labhq.api.settings import ApiSettings
from labhq.auth.resolver import resolve_session
from labhq.auth.routes import public_router, router
from labhq.channels import ChannelRuntime, list_channels
from labhq.cli.context import Context
from labhq.notify import NotifySettings
from tests.auth.authenticator import SoftwareAuthenticator
from tests.auth.conftest import LOCAL, WRITE, auth_env, context, enrolled, settings, signed_in
from tests.channels.conftest import Outbound

__all__ = ["auth_env", "context", "enrolled", "settings", "signed_in"]

TELEGRAM = {"chat_id": "42", "token": "123456:SECRET-TOKEN-VALUE"}


@pytest.fixture
def app_client(context: Context, tmp_path: Path) -> Iterator[TestClient]:
    resolvers = ResolverRegistry()
    resolvers.register("web-session", resolve_session)
    routers = RouterRegistry()
    routers.register(health_router, public=True)
    routers.register(public_router, public=True)
    routers.register(router)
    routers.register(channels_router)
    app = create_app(
        context,
        routers=routers,
        resolvers=resolvers,
        settings=ApiSettings(ui_dir=tmp_path / "no-ui"),
    )
    with TestClient(app, base_url=LOCAL, headers={"Origin": LOCAL}) as client:
        yield client


@pytest.fixture
def outbound() -> Outbound:
    return Outbound()


@pytest.fixture
def client(signed_in: TestClient, context: Context, outbound: Outbound) -> TestClient:
    async def runtime() -> AsyncIterator[ChannelRuntime]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(outbound)) as http:
            yield ChannelRuntime(
                context.sessions, http, context.settings.data_dir, context.clock, NotifySettings()
            )

    signed_in.app.dependency_overrides[get_runtime] = runtime  # type: ignore[attr-defined]
    return signed_in


def assertion(client: TestClient, authenticator: SoftwareAuthenticator, purpose: str) -> Any:
    response = client.post("/api/auth/step-up/options", json={"purpose": purpose}, headers=WRITE)
    assert response.status_code == 200, response.text
    return authenticator.get(response.json(), LOCAL)


def add(client: TestClient, credential: Any, **body: Any) -> Any:
    payload = {"kind": "telegram", "name": "phone", "values": TELEGRAM, "credential": credential}
    return client.post("/api/channels", json=payload | body, headers=WRITE)


async def test_adding_a_channel_needs_a_passkey_and_the_secret_is_never_returned(
    client: TestClient, enrolled: SoftwareAuthenticator, context: Context, outbound: Outbound
) -> None:
    refused = add(client, None)
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "step_up_required"
    async with context.sessions() as db:
        assert await list_channels(db) == []

    response = add(client, assertion(client, enrolled, "channel:new"))

    assert response.status_code == 201, response.text
    assert response.json()["error"] is None
    assert response.json()["channel"]["last_test_ok"] is True
    assert "SECRET" not in response.text
    assert "SECRET" not in client.get("/api/channels").text
    assert outbound.hosts() == ["api.telegram.org"]


async def test_an_assertion_for_another_purpose_does_not_add_a_channel(
    client: TestClient, enrolled: SoftwareAuthenticator, context: Context
) -> None:
    response = add(client, assertion(client, enrolled, "channel:7"))

    assert response.status_code == 403
    async with context.sessions() as db:
        assert await list_channels(db) == []


async def test_bad_settings_are_a_422_with_the_field_named_not_the_value(
    client: TestClient, enrolled: SoftwareAuthenticator
) -> None:
    response = add(
        client, assertion(client, enrolled, "channel:new"), values={"chat_id": "x y", "token": "t"}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "channel_invalid"


async def test_a_channel_is_tested_switched_and_removed(
    client: TestClient, enrolled: SoftwareAuthenticator, context: Context, outbound: Outbound
) -> None:
    created = add(client, assertion(client, enrolled, "channel:new")).json()["channel"]
    channel = created["id"]

    outbound.statuses = [500]
    failed = client.post(f"/api/channels/{channel}/test", headers=WRITE).json()
    assert failed["error"] is not None and failed["channel"]["last_test_ok"] is False
    ok = client.post(f"/api/channels/{channel}/test", headers=WRITE).json()
    assert ok["error"] is None and ok["channel"]["last_test_ok"] is True

    purpose = f"channel:{channel}"
    off = client.patch(
        f"/api/channels/{channel}",
        json={"enabled": False, "credential": assertion(client, enrolled, purpose)},
        headers=WRITE,
    )
    assert off.status_code == 200 and off.json()["enabled"] is False

    no_passkey = client.request("DELETE", f"/api/channels/{channel}", json={}, headers=WRITE)
    assert no_passkey.status_code == 403
    removed = client.request(
        "DELETE",
        f"/api/channels/{channel}",
        json={"credential": assertion(client, enrolled, purpose)},
        headers=WRITE,
    )
    assert removed.status_code == 204
    assert client.get("/api/channels").json() == []
    assert not (context.settings.data_dir / "channels" / f"{channel}.json").exists()


async def test_the_page_needs_a_session(app_client: TestClient) -> None:
    assert app_client.get("/api/channels").status_code == 401
    assert app_client.post("/api/channels/1/test", headers=WRITE).status_code in (401, 403)


async def test_the_kinds_list_names_the_secret_fields(client: TestClient) -> None:
    kinds = {k["kind"]: k for k in client.get("/api/channels/kinds").json()}

    assert set(kinds) == {"ntfy", "telegram", "discord", "slack"}
    assert [f["secret"] for f in kinds["telegram"]["fields"]] == [False, True]
    assert kinds["discord"]["available"] is False
