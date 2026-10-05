"""The project page can request an existing tmux agent as manager."""

from pathlib import Path
from types import SimpleNamespace

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
