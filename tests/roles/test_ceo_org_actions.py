"""Adopting sessions, meetings and priorities run unasked, and every action names the CEO."""

from pathlib import Path
from typing import Any

import pytest

from labhq.adoption import ADOPT_AGENT
from labhq.adoption.observe import OwnerTmux
from labhq.adoption.request import ADOPT_SAVED_SESSION
from labhq.adoption.saved import SavedSession
from labhq.approvals import Executor
from labhq.ceoorg.background import settled
from labhq.db.enums import ApprovalStatus, MeetingStatus
from labhq.db.models import Approval, Meeting, Project, Run, RunEvent, Task
from tests.roles.conftest import Org
from tests.roles.test_ceo_org_projects import FakeProcess

SESSION = "0f4c1a52-3b7e-4c1d-9a55-6a1e9d3c7b10"


async def ceo_actions(org: Org) -> set[tuple[str, str]]:
    events = [e for e in await org.all(RunEvent) if e.kind == "ceo_action"]
    return {(e.payload["tool"], e.payload["actor"]) for e in events}


async def start_ceo_run(org: Org) -> int:
    async with org.sessions() as db:
        run = Run(agent_id=org.ceo, adapter="fake", created_at=org.clock.now())
        db.add(run)
        await db.commit()
        return run.id


async def orphan(org: Org, folder: Path) -> int:
    folder.mkdir()
    now = org.clock.now()
    async with org.sessions() as db:
        project = Project(name=folder.name, repo_path=str(folder), created_at=now, updated_at=now)
        db.add(project)
        await db.commit()
        return project.id


def recording_executor(org: Org, action: str, seen: list[dict[str, Any]]) -> None:
    def run(payload: Any) -> dict[str, Any]:
        seen.append(dict(payload))
        return {"adopted": True}

    org.executors.register(action, Executor(run=run), replace=True)


async def test_the_ceo_resumes_a_saved_session_as_a_manager_without_asking(
    org: Org, monkeypatch: pytest.MonkeyPatch
) -> None:
    await start_ceo_run(org)
    await orphan(org, org.root / "legacy")
    monkeypatch.setattr(
        "labhq.adoption.request.find_saved_session",
        lambda kind, cwd, session_id: SavedSession(kind, session_id, org.clock.now()),
    )
    seen: list[dict[str, Any]] = []
    recording_executor(org, ADOPT_SAVED_SESSION, seen)

    answer = await org.call(
        "assign_saved_session", org.ceo, project="legacy", kind="claude-code", session_id=SESSION
    )
    await settled()

    [approval] = await org.approvals()
    assert approval.type == ADOPT_SAVED_SESSION
    assert (approval.status, approval.decided_by, approval.confirmation_kind) == (
        ApprovalStatus.EXECUTED,
        f"agent:{org.ceo}",
        "ceo",
    )
    assert [(p["project"], p["session_id"]) for p in seen] == [("legacy", SESSION)]
    assert f"A{approval.id}" in answer
    assert ("assign_saved_session", f"agent:{org.ceo}") in await ceo_actions(org)


async def test_the_ceo_adopts_a_running_session_as_a_manager(
    org: Org, monkeypatch: pytest.MonkeyPatch
) -> None:
    await start_ceo_run(org)
    folder = org.root / "live"
    await orphan(org, folder)
    org.processes.append(FakeProcess(4201, ["claude"], folder))
    monkeypatch.setattr(OwnerTmux, "pane_of", lambda self, pid: "%1")
    seen: list[dict[str, Any]] = []
    recording_executor(org, ADOPT_AGENT, seen)

    answer = await org.call("adopt_session", org.ceo, project="live", pid=4201)
    await settled()

    [approval] = await org.approvals()
    assert (approval.status, approval.requested_by_agent_id) == (ApprovalStatus.EXECUTED, org.ceo)
    assert [(p["pid"], p["project"]) for p in seen] == [(4201, "live")]
    assert "takes over" in answer
    assert ("adopt_session", f"agent:{org.ceo}") in await ceo_actions(org)


async def test_adopting_a_process_that_is_not_an_agent_is_refused(org: Org) -> None:
    await orphan(org, org.root / "live")

    answer = await org.call("adopt_session", org.ceo, project="live", pid=999_999)

    assert answer.startswith("Refused:") or "not a running agent" in answer
    assert await org.approvals() == []


async def test_set_priority_changes_an_open_task_and_refuses_a_closed_one(org: Org) -> None:
    await start_ceo_run(org)

    answer = await org.call("set_priority", org.ceo, task=org.site_task, priority=9)

    assert (await org.get(Task, org.site_task)).priority == 9
    assert "is now 9 (was 0)" in answer
    assert await org.approvals() == []
    assert ("set_priority", f"agent:{org.ceo}") in await ceo_actions(org)

    async with org.sessions() as db:
        (await db.get_one(Task, org.shop_task)).status = "done"
        await db.commit()
    closed = await org.call("set_priority", org.ceo, task=org.shop_task, priority=1)
    assert closed.startswith("Refused:")


async def test_the_ceo_starts_a_meeting_and_decides_its_light_approval(org: Org) -> None:
    await start_ceo_run(org)

    answer = await org.call("start_meeting", org.ceo, project="site", kind="standup")
    await settled()

    [meeting] = await org.all(Meeting)
    approval = await org.get(Approval, meeting.approval_id or 0)
    assert (approval.decided_by, approval.confirmation_kind) == (f"agent:{org.ceo}", "ceo")
    assert approval.requested_by_agent_id == org.ceo
    assert meeting.status is not MeetingStatus.REQUESTED
    assert f"Meeting {meeting.id}" in answer
    assert ("start_meeting", f"agent:{org.ceo}") in await ceo_actions(org)


async def test_an_unknown_meeting_kind_is_refused(org: Org) -> None:
    answer = await org.call("start_meeting", org.ceo, project="site", kind="party")

    assert "party" in answer
    assert await org.all(Meeting) == []


async def test_every_ceo_org_tool_is_in_the_ceos_tool_set_and_non_ceos_do_not_get_them(
    org: Org,
) -> None:
    from tests.roles.test_org import CEO_ORG_TOOLS

    ceo = {spec.name for spec in org.tools.for_agent("ceo", {})}
    assert set(CEO_ORG_TOOLS) <= ceo
    for role in ("manager", "lead", "worker", "it"):
        assert not set(CEO_ORG_TOOLS) & {spec.name for spec in org.tools.for_agent(role, {})}
    read_only = {spec.name for spec in org.tools if spec.read_only}
    assert {"discover_projects"} <= read_only
    assert not read_only & (set(CEO_ORG_TOOLS) - {"discover_projects"})


async def test_the_actor_is_the_ceo_whatever_the_model_passes(org: Org) -> None:
    run_id = await start_ceo_run(org)

    await org.call("set_priority", org.ceo, task=org.site_task, priority=2)

    [event] = [e for e in await org.all(RunEvent) if e.kind == "ceo_action"]
    assert event.run_id == run_id
    assert event.payload["actor"] == f"agent:{org.ceo}"
