"""The owner assigns one CEO's main and backup kinds for every project."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from labhq.adapters import FakeAdapter, FakeScript, default_registry
from labhq.cli.context import Context
from labhq.db.enums import RunStatus, WakeupStatus
from labhq.db.models import Agent, Run, RunEvent, WakeupRequest
from labhq.runs import RunService
from labhq.scheduler import Scheduler
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

    managers = []
    for name in ("site", "shop"):
        created = signed_in.post(
            "/api/projects",
            json={"name": name, "repo_path": str(repo)},
            headers=WRITE,
        )
        assert created.status_code == 201, created.text
        manager = signed_in.post(
            f"/api/projects/{created.json()['id']}/agents",
            json={"role": "manager", "title": f"{name} manager", "kind": "codex"},
            headers=WRITE,
        )
        assert manager.status_code == 201, manager.text
        assert manager.json()["reports_to"] == ceo_id
        managers.append(manager.json()["id"])

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


def test_an_unavailable_agent_kind_is_refused(
    signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("labhq.adapters.kinds.shutil.which", lambda _: None)

    response = signed_in.put("/api/org/ceo", json={"primary_kind": "codex"}, headers=WRITE)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ceo_assignment_invalid"


async def test_owner_can_talk_to_ceo_and_see_the_answer(
    signed_in: TestClient, context: Context
) -> None:
    assert signed_in.get("/api/org/ceo/messages").json() == []
    missing = signed_in.post("/api/org/ceo/messages", json={"text": "Hello"}, headers=WRITE)
    assert missing.status_code == 409
    assert missing.json()["error"]["code"] == "ceo_unconfigured"

    ceo_id = signed_in.put(
        "/api/org/ceo", json={"primary_kind": "claude", "backup_kind": "codex"}, headers=WRITE
    ).json()["id"]
    sent = signed_in.post(
        "/api/org/ceo/messages", json={"text": "  How are the projects?  "}, headers=WRITE
    )
    assert sent.status_code == 202, sent.text
    assert (sent.json()["text"], sent.json()["status"]) == ("How are the projects?", "queued")
    pending = signed_in.get("/api/org/ceo/messages").json()
    assert pending[0]["id"] == sent.json()["id"]
    assert pending[0]["reply"] is None
    busy = signed_in.post("/api/org/ceo/messages", json={"text": "One more"}, headers=WRITE)
    assert busy.status_code == 409
    assert busy.json()["error"]["code"] == "ceo_busy"

    async with context.sessions() as db:
        request = await db.get_one(WakeupRequest, sent.json()["id"])
        now = context.clock.now()
        run = Run(
            agent_id=ceo_id,
            task_id=None,
            adapter="claude",
            status=RunStatus.SUCCEEDED,
            created_at=now,
            started_at=now,
            finished_at=now,
            heartbeat_at=now,
        )
        db.add(run)
        await db.flush()
        request.run_id = run.id
        request.status = WakeupStatus.DISPATCHED
        db.add(
            RunEvent(
                run_id=run.id,
                seq=1,
                kind="final_answer",
                payload={"text": "Both projects are moving."},
                created_at=now,
            )
        )
        await db.commit()

    answered = signed_in.get("/api/org/ceo/messages").json()
    assert (answered[0]["reply"], answered[0]["status"]) == (
        "Both projects are moving.",
        "answered",
    )
    followup = signed_in.post("/api/org/ceo/messages", json={"text": "What next?"}, headers=WRITE)
    assert followup.status_code == 202, followup.text
    async with context.sessions() as db:
        request = await db.get_one(WakeupRequest, followup.json()["id"])
    assert "Both projects are moving." in request.reason
    assert "How are the projects?" in request.reason


def test_ceo_chat_requires_a_session(app_client: TestClient) -> None:
    assert app_client.get("/api/org/ceo/messages").status_code == 401
    assert (
        app_client.post("/api/org/ceo/messages", json={"text": "Hello"}, headers=WRITE).status_code
        == 401
    )


async def test_direct_message_runs_through_the_ceo_and_returns_its_real_reply(
    signed_in: TestClient, context: Context
) -> None:
    signed_in.put(
        "/api/org/ceo", json={"primary_kind": "claude", "backup_kind": "codex"}, headers=WRITE
    )
    sent = signed_in.post(
        "/api/org/ceo/messages", json={"text": "Give me a status update"}, headers=WRITE
    )
    assert sent.status_code == 202, sent.text
    fake = FakeScript(text="The projects are on track.")
    registry = default_registry.copy()
    registry.register("claude", lambda: FakeAdapter(fake), replace=True)
    scheduler = Scheduler(
        context.sessions,
        clock=context.clock,
        runs=RunService(context.sessions, clock=context.clock, registry=registry),
    )

    report = await scheduler.tick()
    assert len(report.started) == 1
    await scheduler.settle()

    assert "Give me a status update" in fake.requests[0].prompt
    assert fake.requests[0].cwd is not None
    turns = signed_in.get("/api/org/ceo/messages").json()
    assert turns[0]["status"] == "answered"
    assert turns[0]["reply"] == "The projects are on track."
