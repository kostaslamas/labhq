"""The scan folders over HTTP: readable with a session, changed only with a passkey."""

import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from labhq.api.app import create_app
from labhq.api.deps import ResolverRegistry
from labhq.api.inventory import router as inventory_router
from labhq.api.inventory import routes as inventory_routes
from labhq.api.routes import RouterRegistry, health_router
from labhq.api.settings import ApiSettings
from labhq.auth.resolver import resolve_session
from labhq.auth.routes import public_router, router
from labhq.cli.context import Context
from labhq.db.models import Project
from tests.auth.authenticator import SoftwareAuthenticator
from tests.auth.conftest import LOCAL, WRITE, auth_env, context, enrolled, settings, signed_in

__all__ = ["auth_env", "context", "enrolled", "settings", "signed_in"]


@pytest.fixture(autouse=True)
def quiet_machine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A scan reads the test's own home and no real process, and starts from no scan."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("psutil.process_iter", lambda *args, **kwargs: iter(()))
    for name in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "CLAUDE_CONFIG_DIR", "CODEX_HOME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(inventory_routes, "_last", inventory_routes.Last())


@pytest.fixture
def app_client(context: Context, tmp_path: Path) -> Iterator[TestClient]:
    resolvers = ResolverRegistry()
    resolvers.register("web-session", resolve_session)
    routers = RouterRegistry()
    routers.register(health_router, public=True)
    routers.register(public_router, public=True)
    routers.register(router)
    routers.register(inventory_router)
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


def put(client: TestClient, enrolled: SoftwareAuthenticator, **body: Any) -> Any:
    payload = {"roots": [], "exclude": [], **body, "credential": assertion(client, enrolled)}
    return client.put("/api/inventory/roots", json=payload, headers=WRITE)


def make_project(folder: Path) -> Path:
    (folder / ".git").mkdir(parents=True)
    return folder


def test_a_fresh_install_is_machine_wide(signed_in: TestClient) -> None:
    body = signed_in.get("/api/inventory/roots").json()

    assert (
        body["machine_wide"] is True and body["roots"] == [] and body["scan"]["scanned_at"] is None
    )


def test_saving_needs_a_passkey(signed_in: TestClient, tmp_path: Path) -> None:
    response = signed_in.put("/api/inventory/roots", json={"roots": [str(tmp_path)]}, headers=WRITE)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "step_up_required"
    assert signed_in.get("/api/inventory/roots").json()["machine_wide"] is True


def test_a_passkey_saves_the_roots_and_they_persist(
    signed_in: TestClient, enrolled: SoftwareAuthenticator, tmp_path: Path
) -> None:
    folder = tmp_path / "dev"
    folder.mkdir()

    saved = put(signed_in, enrolled, roots=[str(folder)])

    assert saved.status_code == 200, saved.text
    (root,) = saved.json()["scope"]["roots"]
    assert root == {"path": str(folder.resolve()), "source": "stored", "removable": True}
    assert signed_in.get("/api/inventory/roots").json()["machine_wide"] is False
    assert put(signed_in, enrolled, roots=[]).json()["scope"]["machine_wide"] is True


def test_the_filesystem_root_is_a_422_and_nothing_changes(
    signed_in: TestClient, enrolled: SoftwareAuthenticator, tmp_path: Path
) -> None:
    folder = tmp_path / "dev"
    folder.mkdir()
    put(signed_in, enrolled, roots=[str(folder)])

    refused = put(signed_in, enrolled, roots=["/"])

    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "root_invalid"
    (root,) = signed_in.get("/api/inventory/roots").json()["roots"]
    assert root["path"] == str(folder.resolve())


def test_the_home_folder_is_saved_with_a_warning(
    signed_in: TestClient, enrolled: SoftwareAuthenticator, tmp_path: Path
) -> None:
    saved = put(signed_in, enrolled, roots=[str(tmp_path / "home")])

    assert saved.status_code == 200
    assert "home folder" in saved.json()["warnings"][0]


def test_scan_now_lists_found_projects_without_sessions_and_hides_added_ones(
    signed_in: TestClient, enrolled: SoftwareAuthenticator, tmp_path: Path, context: Context
) -> None:
    root = tmp_path / "dev"
    new, added = make_project(root / "new"), make_project(root / "added")
    put(signed_in, enrolled, roots=[str(root)])

    async def add_project() -> None:
        async with context.sessions() as db:
            db.add(
                Project(
                    name="added",
                    repo_path=str(added),
                    created_at=context.clock.now(),
                    updated_at=context.clock.now(),
                )
            )
            await db.commit()

    asyncio.run(add_project())

    scanned = signed_in.post("/api/inventory/scan", headers=WRITE).json()

    assert [f["name"] for f in scanned["found"]] == ["new"]
    assert scanned["found"][0]["markers"] == ["git"]
    assert scanned["found"][0]["relative"] == "new"
    assert scanned["scanned_at"] is not None and scanned["capped"] is False
    assert signed_in.get("/api/inventory/scan").json()["found"][0]["path"] == str(new.resolve())


def test_not_interested_records_an_exclusion_with_a_passkey(
    signed_in: TestClient, enrolled: SoftwareAuthenticator, tmp_path: Path
) -> None:
    root = tmp_path / "dev"
    skip, keep = make_project(root / "skip"), make_project(root / "keep")
    put(signed_in, enrolled, roots=[str(root)])
    signed_in.post("/api/inventory/scan", headers=WRITE)

    bare = signed_in.post("/api/inventory/exclusions", json={"path": str(skip)}, headers=WRITE)
    done = signed_in.post(
        "/api/inventory/exclusions",
        json={"path": str(skip), "credential": assertion(signed_in, enrolled)},
        headers=WRITE,
    )

    assert bare.status_code == 403
    assert done.status_code == 201, done.text
    assert [f["path"] for f in done.json()["scan"]["found"]] == [str(keep.resolve())]
    assert [e["path"] for e in done.json()["exclude"]] == [str(skip.resolve())]
    rescanned = signed_in.post("/api/inventory/scan", headers=WRITE).json()
    assert [f["name"] for f in rescanned["found"]] == ["keep"]


def test_a_root_from_the_environment_is_listed_and_cannot_be_removed_here(
    signed_in: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from labhq.inventory.settings import get_inventory_settings

    monkeypatch.setenv("LABHQ_INVENTORY_ROOTS", f'["{tmp_path}"]')
    get_inventory_settings.cache_clear()
    try:
        (root,) = signed_in.get("/api/inventory/roots").json()["roots"]
    finally:
        get_inventory_settings.cache_clear()

    assert root["source"] == "environment" and root["removable"] is False
