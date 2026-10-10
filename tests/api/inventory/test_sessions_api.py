"""The Sessions view and its actions: every action records an approval, nothing runs by itself."""

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from labhq.cli.context import Context
from labhq.db.models import Approval, Project
from tests.api.inventory.conftest import (
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
from tests.inventory import stores_fixture as fx

__all__ = ["auth_env", "context", "enrolled", "settings", "signed_in"]


def scan_with_a_session(
    client: TestClient, enrolled: SoftwareAuthenticator, home: Path, root: Path
) -> Path:
    repo = root / "party"
    if not repo.exists():
        make_project(repo)
    fx.claude(home, repo)
    assert put_roots(client, enrolled, roots=[str(root)]).status_code == 200
    assert client.post("/api/inventory/scan", headers=WRITE).status_code == 200
    return repo


def test_before_any_scan_the_sessions_view_is_empty(signed_in: TestClient) -> None:
    body = signed_in.get("/api/inventory/sessions").json()

    assert body["scanned_at"] is None and body["projects"] == [] and body["tools"] == []


def test_a_scan_lists_projects_sessions_and_a_proposed_action_without_any_text(
    signed_in: TestClient, enrolled: SoftwareAuthenticator, quiet_machine: Path, tmp_path: Path
) -> None:
    repo = scan_with_a_session(signed_in, enrolled, quiet_machine, tmp_path / "dev")

    response = signed_in.get("/api/inventory/sessions")

    (project,) = response.json()["projects"]
    assert project["root"] == str(repo.resolve()) and project["project_id"] is None
    (session,) = project["sessions"]
    assert session["tool"] == "claude-code" and session["state"] == "idle"
    assert session["proposal"]["action"] in {"continue", "keep as history", "close"}
    assert session["pid"] is None and session["resumable"] is True
    assert project["git"]["branch"] == "main" or project["git"]["branch"] is None
    assert fx.SECRET_TEXT not in response.text and fx.CLAUDE_ID in response.text


def test_the_cards_of_added_projects_show_their_session_counts(
    signed_in: TestClient,
    enrolled: SoftwareAuthenticator,
    quiet_machine: Path,
    tmp_path: Path,
    context: Context,
) -> None:
    async def add(repo: Path) -> None:
        async with context.sessions() as db:
            now = context.clock.now()
            db.add(Project(name="party", repo_path=str(repo), created_at=now, updated_at=now))
            await db.commit()

    repo = make_project(tmp_path / "dev" / "party")
    asyncio.run(add(repo))
    before = signed_in.get("/api/projects").json()["items"][0]
    scan_with_a_session(signed_in, enrolled, quiet_machine, tmp_path / "dev")
    after = signed_in.get("/api/projects").json()["items"][0]
    listed = signed_in.get("/api/inventory/sessions").json()["projects"][0]

    assert before["sessions"] is None
    assert after["sessions"] == {"total": 1, "running": 0, "waiting": 0, "idle": 1}
    assert listed["project_id"] == after["id"]


def test_an_action_needs_a_scan_first(signed_in: TestClient) -> None:
    response = signed_in.post(
        "/api/inventory/actions/continue",
        json={"project": "party", "session_id": fx.CLAUDE_ID},
        headers=WRITE,
    )

    assert response.status_code == 409 and response.json()["error"]["code"] == "scan_first"


def test_continue_records_an_adoption_approval_and_starts_nothing(
    signed_in: TestClient,
    enrolled: SoftwareAuthenticator,
    quiet_machine: Path,
    tmp_path: Path,
    context: Context,
) -> None:
    scan_with_a_session(signed_in, enrolled, quiet_machine, tmp_path / "dev")

    response = signed_in.post(
        "/api/inventory/actions/continue",
        json={"project": "party", "session_id": fx.CLAUDE_ID},
        headers=WRITE,
    )

    assert response.status_code == 201, response.text
    approval_id = response.json()["approval_id"]

    async def stored() -> list[Approval]:
        async with context.sessions() as db:
            return list(await db.scalars(select(Approval)))

    (approval,) = asyncio.run(stored())
    assert approval.id == approval_id and approval.status.value == "pending"


def test_an_unknown_session_is_refused_with_the_reason(
    signed_in: TestClient, enrolled: SoftwareAuthenticator, quiet_machine: Path, tmp_path: Path
) -> None:
    scan_with_a_session(signed_in, enrolled, quiet_machine, tmp_path / "dev")

    response = signed_in.post(
        "/api/inventory/actions/close", json={"project": "party", "pid": 1}, headers=WRITE
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "inventory_action_refused"


def test_analyse_shows_the_estimate_and_records_the_approval_that_would_start_it(
    signed_in: TestClient,
    enrolled: SoftwareAuthenticator,
    quiet_machine: Path,
    tmp_path: Path,
    context: Context,
) -> None:
    scan_with_a_session(signed_in, enrolled, quiet_machine, tmp_path / "dev")

    response = signed_in.post(
        "/api/inventory/actions/analyse", json={"project": "party"}, headers=WRITE
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert "Approve approval" in body["summary"] and "tokens" in body["summary"]

    async def stored() -> list[Approval]:
        async with context.sessions() as db:
            return list(await db.scalars(select(Approval)))

    (approval,) = asyncio.run(stored())
    assert approval.id == body["approval_id"] and approval.status.value == "pending"


def test_analysing_an_unknown_project_is_refused_and_records_nothing(
    signed_in: TestClient, context: Context
) -> None:
    response = signed_in.post(
        "/api/inventory/actions/analyse", json={"project": "nothing"}, headers=WRITE
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "inventory_action_refused"

    async def count() -> int:
        async with context.sessions() as db:
            return len(list(await db.scalars(select(Approval))))

    assert asyncio.run(count()) == 0


def test_a_folder_manager_is_proposed_and_requested_as_an_approval(
    signed_in: TestClient, enrolled: SoftwareAuthenticator, tmp_path: Path
) -> None:
    root = tmp_path / "dev"
    for name in ("a", "b"):
        make_project(root / "games" / name)
    put_roots(signed_in, enrolled, roots=[str(root)])
    signed_in.post("/api/inventory/scan", headers=WRITE)

    (folder,) = signed_in.get("/api/inventory/sessions").json()["folders"]
    asked = signed_in.post(
        "/api/inventory/actions/folder", json={"folder": folder["folder"]}, headers=WRITE
    )

    assert asked.status_code == 201, asked.text
    assert asked.json()["approval_id"] is not None
    nope = signed_in.post("/api/inventory/actions/folder", json={"folder": "x"}, headers=WRITE)
    assert nope.status_code == 422
