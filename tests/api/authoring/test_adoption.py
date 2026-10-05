"""The project page can request an existing tmux agent as manager."""

import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from labhq.adoption.discovery import RunningAgent
from tests.auth.conftest import WRITE


async def test_project_can_list_and_request_a_running_tmux_manager(
    signed_in: TestClient, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = signed_in.post(
        "/api/projects",
        json={"name": "site", "repo_path": str(repo)},
        headers=WRITE,
    )
    assert created.status_code == 201
    project_id = created.json()["id"]
    candidate = RunningAgent(1234, "codex", repo, 1.0, ("codex",))
    requested: list[tuple[int, str | None, bool]] = []

    class FakeAdoptions:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def discover(self) -> list[RunningAgent]:
            return [candidate]

        async def request(
            self, pid: int, *, project: str | None, require_tmux: bool
        ) -> SimpleNamespace:
            requested.append((pid, project, require_tmux))
            return SimpleNamespace(
                approval=SimpleNamespace(id=42), warnings=("Review before moving",)
            )

    monkeypatch.setattr("labhq.api.authoring.routes.Adoptions", FakeAdoptions)
    monkeypatch.setattr("labhq.api.authoring.routes.OwnerTmux.pane_of", lambda self, pid: "%1")

    listed = signed_in.get(f"/api/projects/{project_id}/running-managers")
    assert listed.status_code == 200
    assert listed.json() == [{"pid": 1234, "kind": "codex", "cwd": str(repo), "pane": "%1"}]
    response = signed_in.post(
        f"/api/projects/{project_id}/adopt-manager", json={"pid": 1234}, headers=WRITE
    )
    assert response.status_code == 202
    assert response.json() == {"approval_id": 42, "warnings": ["Review before moving"]}
    assert requested == [(1234, "site", True)]


@pytest.mark.posix_only("saved CLI sessions run through the tmux adapter")
async def test_project_lists_and_requests_an_exact_saved_session(
    signed_in: TestClient, repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    created = signed_in.post(
        "/api/projects", json={"name": "saved-site", "repo_path": str(repo)}, headers=WRITE
    )
    assert created.status_code == 201
    project_id = created.json()["id"]
    store = tmp_path / "codex" / "sessions" / "2026" / "10" / "05"
    store.mkdir(parents=True)
    selected = str(uuid4())
    (store / f"rollout-{selected}.jsonl").write_text(
        json.dumps({"type": "session_meta", "payload": {"id": selected, "cwd": str(repo)}}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))

    listed = signed_in.get(f"/api/projects/{project_id}/saved-sessions?kind=codex")
    assert listed.status_code == 200
    assert [(row["kind"], row["session_id"]) for row in listed.json()] == [("codex", selected)]
    missing = signed_in.post(
        f"/api/projects/{project_id}/assign-saved-session",
        json={"kind": "codex", "session_id": str(uuid4())},
        headers=WRITE,
    )
    assert missing.status_code == 422
    assigned = signed_in.post(
        f"/api/projects/{project_id}/assign-saved-session",
        json={"kind": "codex", "session_id": selected},
        headers=WRITE,
    )
    assert assigned.status_code == 202
    assert assigned.json()["approval_id"] > 0
