"""The scan folders over HTTP: readable with a session, changed only with a passkey."""

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from labhq.cli.context import Context
from labhq.db.models import Project
from tests.api.inventory.conftest import (
    assertion,
    auth_env,
    context,
    enrolled,
    make_project,
    put_roots,
    settings,
    signed_in,
)
from tests.auth.authenticator import SoftwareAuthenticator
from tests.auth.conftest import WRITE

__all__ = ["auth_env", "context", "enrolled", "settings", "signed_in"]


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

    saved = put_roots(signed_in, enrolled, roots=[str(folder)])

    assert saved.status_code == 200, saved.text
    (root,) = saved.json()["scope"]["roots"]
    assert root == {"path": str(folder.resolve()), "source": "stored", "removable": True}
    assert signed_in.get("/api/inventory/roots").json()["machine_wide"] is False
    assert put_roots(signed_in, enrolled, roots=[]).json()["scope"]["machine_wide"] is True


def test_the_filesystem_root_is_a_422_and_nothing_changes(
    signed_in: TestClient, enrolled: SoftwareAuthenticator, tmp_path: Path
) -> None:
    folder = tmp_path / "dev"
    folder.mkdir()
    put_roots(signed_in, enrolled, roots=[str(folder)])

    refused = put_roots(signed_in, enrolled, roots=["/"])

    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "root_invalid"
    (root,) = signed_in.get("/api/inventory/roots").json()["roots"]
    assert root["path"] == str(folder.resolve())


def test_the_home_folder_is_saved_with_a_warning(
    signed_in: TestClient, enrolled: SoftwareAuthenticator, tmp_path: Path
) -> None:
    saved = put_roots(signed_in, enrolled, roots=[str(tmp_path / "home")])

    assert saved.status_code == 200
    assert "home folder" in saved.json()["warnings"][0]


def test_scan_now_lists_found_projects_without_sessions_and_hides_added_ones(
    signed_in: TestClient, enrolled: SoftwareAuthenticator, tmp_path: Path, context: Context
) -> None:
    root = tmp_path / "dev"
    new, added = make_project(root / "new"), make_project(root / "added")
    put_roots(signed_in, enrolled, roots=[str(root)])

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
    put_roots(signed_in, enrolled, roots=[str(root)])
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
