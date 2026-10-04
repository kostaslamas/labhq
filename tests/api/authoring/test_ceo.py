"""The owner assigns one CEO's main and backup kinds for every project."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from labhq.adapters import default_registry
from labhq.cli.context import Context
from labhq.db.models import Agent
from labhq.hierarchy import Hierarchy
from tests.auth.conftest import WRITE


@pytest.fixture(autouse=True)
def available_kinds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("labhq.adapters.kinds._claude_binary", lambda: "/bin/claude")
    monkeypatch.setattr("labhq.adapters.kinds.shutil.which", lambda _: "/bin/codex")


async def test_one_ceo_can_be_configured_and_updated_without_losing_its_identity(
    signed_in: TestClient, context: Context, repo: Path
) -> None:
    empty = signed_in.get("/api/org/ceo")
    assert empty.status_code == 200
    assert empty.json() == {"id": None, "primary_kind": None, "backup_kind": None}

    first = signed_in.put(
        "/api/org/ceo",
        json={"primary_kind": "claude", "backup_kind": "codex"},
        headers=WRITE,
    )
    assert first.status_code == 200, first.text
    ceo_id = first.json()["id"]
    assert first.json() == {
        "id": ceo_id,
        "primary_kind": "claude",
        "backup_kind": "codex",
    }
    assert signed_in.get("/api/org/ceo").json() == first.json()

    hierarchy = Hierarchy(
        context.sessions, clock=context.clock, adapters=default_registry.adapter_keys()
    )
    managers = []
    for name in ("site", "shop"):
        created = signed_in.post(
            "/api/projects",
            json={"name": name, "repo_path": str(repo)},
            headers=WRITE,
        )
        assert created.status_code == 201, created.text
        managers.append((await hierarchy.assign_manager(name)).manager.id)

    changed = signed_in.put(
        "/api/org/ceo",
        json={"primary_kind": "codex", "backup_kind": "claude"},
        headers=WRITE,
    )
    assert changed.status_code == 200, changed.text
    assert changed.json() == {
        "id": ceo_id,
        "primary_kind": "codex",
        "backup_kind": "claude",
    }
    async with context.sessions() as db:
        agents = list(await db.scalars(select(Agent)))
    assert len(agents) == 3
    ceo = next(agent for agent in agents if agent.role == "ceo")
    assert (ceo.id, ceo.role, ceo.project_id, ceo.adapter) == (ceo_id, "ceo", None, "tmux")
    assert [agent.reports_to for agent in agents if agent.id in managers] == [ceo_id, ceo_id]
    assert ceo.config == {
        "agent": "codex",
        "fallback_agent": "claude",
        "fallback_adapter": "claude",
    }

    without_backup = signed_in.put(
        "/api/org/ceo",
        json={"primary_kind": "codex", "backup_kind": None},
        headers=WRITE,
    )
    assert without_backup.json() == {
        "id": ceo_id,
        "primary_kind": "codex",
        "backup_kind": None,
    }
    async with context.sessions() as db:
        ceo = await db.get_one(Agent, ceo_id)
    assert ceo.config == {"agent": "codex"}


@pytest.mark.parametrize(
    ("primary", "backup"),
    [("codex", "codex"), ("unknown", None)],
)
def test_invalid_assignments_do_not_create_a_ceo(
    signed_in: TestClient, primary: str, backup: str | None
) -> None:
    response = signed_in.put(
        "/api/org/ceo",
        json={"primary_kind": primary, "backup_kind": backup},
        headers=WRITE,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ceo_assignment_invalid"
    assert signed_in.get("/api/org/ceo").json()["id"] is None


def test_ceo_assignment_requires_a_session(app_client: TestClient) -> None:
    assert app_client.get("/api/org/ceo").status_code == 401
    assert (
        app_client.put("/api/org/ceo", json={"primary_kind": "claude"}, headers=WRITE).status_code
        == 401
    )
