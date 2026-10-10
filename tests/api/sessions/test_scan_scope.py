"""The Session scan page over HTTP: readable with a session, changed only with a passkey."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from labhq.api.app import create_app
from labhq.api.deps import ResolverRegistry
from labhq.api.routes import RouterRegistry, health_router
from labhq.api.sessions import router as sessions_router
from labhq.api.settings import ApiSettings
from labhq.auth.resolver import resolve_session
from labhq.auth.routes import public_router, router
from labhq.cli.context import Context
from tests.auth.authenticator import SoftwareAuthenticator
from tests.auth.conftest import LOCAL, WRITE, auth_env, context, enrolled, settings, signed_in

__all__ = ["auth_env", "context", "enrolled", "settings", "signed_in"]


@pytest.fixture
def app_client(context: Context, tmp_path: Path) -> Iterator[TestClient]:
    resolvers = ResolverRegistry()
    resolvers.register("web-session", resolve_session)
    routers = RouterRegistry()
    routers.register(health_router, public=True)
    routers.register(public_router, public=True)
    routers.register(router)
    routers.register(sessions_router)
    app = create_app(
        context,
        routers=routers,
        resolvers=resolvers,
        settings=ApiSettings(ui_dir=tmp_path / "no-ui"),
    )
    with TestClient(app, base_url=LOCAL, headers={"Origin": LOCAL}) as client:
        yield client


def assertion(client: TestClient, authenticator: SoftwareAuthenticator) -> Any:
    response = client.post(
        "/api/auth/step-up/options", json={"purpose": "session_scan:roots"}, headers=WRITE
    )
    assert response.status_code == 200, response.text
    return authenticator.get(response.json(), LOCAL)


def test_a_fresh_install_is_machine_wide(signed_in: TestClient) -> None:
    body = signed_in.get("/api/session-scan").json()

    assert body["machine_wide"] is True and body["roots"] == []


def test_adding_needs_a_passkey(signed_in: TestClient, tmp_path: Path) -> None:
    response = signed_in.post(
        "/api/session-scan/roots", json={"path": str(tmp_path)}, headers=WRITE
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "step_up_required"
    assert signed_in.get("/api/session-scan").json()["machine_wide"] is True


def test_a_passkey_adds_then_removes_a_folder(
    signed_in: TestClient, enrolled: SoftwareAuthenticator, tmp_path: Path
) -> None:
    folder = tmp_path / "dev"
    folder.mkdir()
    body = {"path": str(folder), "credential": assertion(signed_in, enrolled)}

    added = signed_in.post("/api/session-scan/roots", json=body, headers=WRITE)

    assert added.status_code == 201, added.text
    (root,) = added.json()["scope"]["roots"]
    assert root == {"path": str(folder.resolve()), "source": "stored", "removable": True}
    assert signed_in.get("/api/session-scan").json()["machine_wide"] is False

    gone = {"path": str(folder), "credential": assertion(signed_in, enrolled)}
    removed = signed_in.request("DELETE", "/api/session-scan/roots", json=gone, headers=WRITE)

    assert removed.status_code == 200 and removed.json()["machine_wide"] is True


def test_the_filesystem_root_is_a_422_and_nothing_changes(
    signed_in: TestClient, enrolled: SoftwareAuthenticator
) -> None:
    body = {"path": "/", "credential": assertion(signed_in, enrolled)}

    response = signed_in.post("/api/session-scan/roots", json=body, headers=WRITE)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "root_invalid"
    assert signed_in.get("/api/session-scan").json()["roots"] == []


def test_removing_an_unknown_folder_is_a_404(
    signed_in: TestClient, enrolled: SoftwareAuthenticator, tmp_path: Path
) -> None:
    body = {"path": str(tmp_path), "credential": assertion(signed_in, enrolled)}

    response = signed_in.request("DELETE", "/api/session-scan/roots", json=body, headers=WRITE)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "root_not_found"


def test_a_root_from_the_environment_is_listed_and_cannot_be_removed_here(
    signed_in: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LABHQ_INVENTORY_ROOTS", f'["{tmp_path}"]')
    from labhq.inventory.settings import get_inventory_settings

    get_inventory_settings.cache_clear()
    try:
        (root,) = signed_in.get("/api/session-scan").json()["roots"]
    finally:
        get_inventory_settings.cache_clear()

    assert root["source"] == "environment" and root["removable"] is False
