"""A standup from request to minutes, with fake agents (plan §10, Phase 3)."""

import pytest
from sqlalchemy import select

from labhq.db.enums import (
    ApprovalStatus,
    MeetingStatus,
    TranscriptSource,
    WakeupSource,
    WakeupStatus,
)
from labhq.db.models import Approval, Task, WakeupRequest
from labhq.meetings import MeetingNotApprovedError, read_minutes
from tests.meetings.conftest import World


async def test_a_standup_produces_participants_transcript_decisions_and_action_items(
    world: World,
) -> None:
    world.stage.minutes.append(world.minutes_json())
    meeting_id = await world.approved_meeting()

    meeting = await world.service.start(meeting_id)

    assert meeting.status is MeetingStatus.ENDED
    async with world.sessions() as db:
        minutes = await read_minutes(db, meeting_id)
        tasks = {task.id: task for task in await db.scalars(select(Task))}
    assert [p.agent_id for p in minutes.participants] == [world.manager_id, world.lead_id]
    agent_turns = [e for e in minutes.transcript if e.source is TranscriptSource.AGENT]
    # Two turns and the facilitator's minutes, each with the run that produced it.
    assert len(agent_turns) == 3
    assert all(entry.run_id is not None for entry in agent_turns)
    assert [d.text for d in minutes.decisions] == ["Ship the parser first"]
    assert len(minutes.action_items) == 1
    item = minutes.action_items[0]
    assert item.decision_id == minutes.decisions[0].id
    task = tasks[item.task_id]
    assert (task.title, task.assignee_id, task.project_id) == (
        "Write parser tests",
        world.lead_id,
        world.project_id,
    )


async def test_the_manager_facilitates_and_speaks_first(world: World) -> None:
    world.stage.minutes.append(world.minutes_json())
    meeting_id = await world.approved_meeting()

    await world.service.start(meeting_id)

    meeting = await world.meeting(meeting_id)
    assert meeting.facilitator_agent_id == world.manager_id
    # A manager's run opens with its memory, so the turn line need not come first.
    first_turn = world.stage.turn_prompts()[0]
    assert "You are Manager (manager)" in first_turn
    assert "You are Backend lead (lead)" in world.stage.turn_prompts()[1]


async def test_an_action_item_assignee_is_woken_as_for_any_assignment(world: World) -> None:
    world.stage.minutes.append(world.minutes_json())
    meeting_id = await world.approved_meeting()

    await world.service.start(meeting_id)

    async with world.sessions() as db:
        wakeups = list(await db.scalars(select(WakeupRequest)))
    assert [(w.agent_id, w.source, w.status) for w in wakeups] == [
        (world.lead_id, WakeupSource.ASSIGNMENT, WakeupStatus.PENDING)
    ]


async def test_requesting_a_meeting_waits_for_the_light_approval(world: World) -> None:
    meeting = await world.service.request(project_id=world.project_id, kind="standup")

    assert meeting.status is MeetingStatus.REQUESTED
    async with world.sessions() as db:
        approval = await db.get_one(Approval, meeting.approval_id)
    assert (approval.type, approval.status) == ("start_meeting", ApprovalStatus.PENDING)
    with pytest.raises(MeetingNotApprovedError):
        await world.service.start(meeting.id)
    assert world.stage.prompts == []


async def test_a_rejected_meeting_is_cancelled_without_a_run(world: World) -> None:
    meeting = await world.service.request(project_id=world.project_id, kind="standup")
    assert meeting.approval_id is not None
    await world.approvals.reject(meeting.approval_id, decider="owner", confirmation="voice")

    started = await world.service.start_decided()

    assert [m.status for m in started] == [MeetingStatus.CANCELLED]
    assert world.stage.prompts == []


async def test_start_decided_runs_approved_meetings(world: World) -> None:
    world.stage.minutes.append(world.minutes_json())
    meeting_id = await world.approved_meeting()

    started = await world.service.start_decided()

    assert [(m.id, m.status) for m in started] == [(meeting_id, MeetingStatus.ENDED)]
