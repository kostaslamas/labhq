"""Shared pieces of the inventory API tests: the app with the inventory routes, a quiet machine."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from labhq.api.app import create_app
from labhq.api.deps import ResolverRegistry
from labhq.api.inventory import router as inventory_router
from labhq.api.inventory import routes as inventory_routes
from labhq.api.inventory.state import LAST
from labhq.api.projects import router as projects_router
from labhq.api.routes import RouterRegistry, health_router
from labhq.api.settings import ApiSettings
from labhq.auth.resolver import resolve_session
from labhq.auth.routes import public_router, router
from labhq.cli.context import Context
from tests.auth.authenticator import SoftwareAuthenticator
from tests.auth.conftest import LOCAL, WRITE, auth_env, context, enrolled, settings, signed_in

__all__ = ["auth_env", "context", "enrolled", "settings", "signed_in"]


@pytest.fixture(autouse=True)
def quiet_machine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A scan reads the test's own home and no real process, and starts from no scan."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("psutil.process_iter", lambda *args, **kwargs: iter(()))
    for name in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "CLAUDE_CONFIG_DIR", "CODEX_HOME"):
        monkeypatch.delenv(name, raising=False)
    LAST.reset()
    # No tool's own status command is started by a test.
    monkeypatch.setattr(inventory_routes, "status_runner", lambda argv, timeout: None)
    return home


@pytest.fixture
def app_client(context: Context, tmp_path: Path) -> Iterator[TestClient]:
    resolvers = ResolverRegistry()
    resolvers.register("web-session", resolve_session)
    routers = RouterRegistry()
    routers.register(health_router, public=True)
    routers.register(public_router, public=True)
    routers.register(router)
    routers.register(inventory_router)
    routers.register(projects_router)
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


def put_roots(client: TestClient, enrolled: SoftwareAuthenticator, **body: Any) -> Any:
    payload = {"roots": [], "exclude": [], **body, "credential": assertion(client, enrolled)}
    return client.put("/api/inventory/roots", json=payload, headers=WRITE)


def make_project(folder: Path) -> Path:
    (folder / ".git").mkdir(parents=True)
    return folder
