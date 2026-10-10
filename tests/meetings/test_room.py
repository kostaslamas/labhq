"""A decision room: owner, CEO and manager in one live thread, bounded by a turn cap."""

import pytest
from sqlalchemy import select

from labhq.approvals import ConfirmationNotAllowedError
from labhq.db.enums import ApprovalStatus, MeetingStatus, TranscriptSource
from labhq.db.models import (
    Approval,
    CeoReport,
    Meeting,
    MeetingActionItem,
    MeetingParticipant,
    Task,
)
from labhq.meetings import (
    MeetingNotApprovedError,
    RoomClosedError,
    add_owner_entry,
    meeting_cost_micros,
    read_minutes,
)
from tests.meetings.conftest import World


async def _report(world: World) -> int:
    async with world.sessions() as db:
        report = CeoReport(
            agent_id=world.ceo_id,
            text="Hire two reviewers for the parser backlog.",
            refs=[],
            created_at=world.clock.now(),
        )
        db.add(report)
        await db.commit()
        return report.id


def _minutes(world: World) -> str:
    # Only the manager can take an action item: the CEO assigns no task of its own.
    return world.minutes_json(decision="One reviewer").replace(
        str(world.lead_id), str(world.manager_id)
    )


async def _room(world: World, *, approve: bool = True) -> int:
    report_id = await _report(world)
    meeting = await world.service.request(
        project_id=world.project_id,
        kind="decision",
        agenda="Should we hire two reviewers?",
        requested_by=world.ceo_id,
        pinned=("report", report_id),
    )
    assert meeting.approval_id is not None
    if approve:
        await world.approvals.approve(meeting.approval_id, decider="owner", confirmation="tap")
    return meeting.id


async def _speakers(world: World, meeting_id: int) -> list[str]:
    async with world.sessions() as db:
        minutes = await read_minutes(db, meeting_id)
    return [e.speaker for e in minutes.transcript]


async def test_the_room_has_the_ceo_and_the_projects_manager(world: World) -> None:
    meeting_id = await _room(world, approve=False)

    async with world.sessions() as db:
        meeting = await db.get_one(Meeting, meeting_id)
        agents = list(
            await db.scalars(
                select(MeetingParticipant.agent_id)
                .where(MeetingParticipant.meeting_id == meeting_id)
                .order_by(MeetingParticipant.id)
            )
        )
        approval = await db.get_one(Approval, meeting.approval_id)

    assert agents == [world.ceo_id, world.manager_id]
    assert meeting.facilitator_agent_id == world.ceo_id
    assert meeting.status is MeetingStatus.REQUESTED
    assert (meeting.pinned_kind, meeting.pinned_id) == ("report", 1)
    # The owner sees the range before approving: 13 runs of 200,000 growing 10% a turn.
    assert meeting.estimate_micros == 4_160_000
    assert approval.payload["estimate_micros"] == meeting.estimate_micros


async def test_the_ceo_cannot_approve_the_start_of_its_own_room(world: World) -> None:
    meeting_id = await _room(world, approve=False)
    meeting = await world.meeting(meeting_id)
    assert meeting.approval_id is not None
    await world.approvals.approve(meeting.approval_id, decider="agent:1", confirmation="ceo")

    with pytest.raises(MeetingNotApprovedError, match="owner's approval"):
        await world.service.start(meeting_id)

    assert (await world.meeting(meeting_id)).status is MeetingStatus.REQUESTED


async def test_the_ceo_opens_and_the_manager_answers(world: World) -> None:
    meeting_id = await _room(world)

    meeting = await world.service.start(meeting_id)

    assert meeting.status is MeetingStatus.RUNNING
    assert await _speakers(world, meeting_id) == ["CEO", "Manager"]
    # Both turns saw the pinned proposal.
    assert all("Hire two reviewers" in prompt for prompt in world.stage.turn_prompts())
    assert world.stage.minutes_prompts() == []


async def test_an_owner_entry_is_recorded_at_once_and_each_agent_answers_it(
    world: World,
) -> None:
    meeting_id = await _room(world)
    await world.service.start(meeting_id)
    before = len(world.stage.turn_prompts())

    entry = await add_owner_entry(
        world.sessions, world.clock, meeting_id=meeting_id, text="Only one reviewer, please."
    )
    assert entry is not None and entry.source is TranscriptSource.OWNER
    # Recorded before any agent has been asked.
    assert len(world.stage.turn_prompts()) == before

    await world.room.advance(meeting_id)

    assert (await _speakers(world, meeting_id))[-3:] == ["Owner", "CEO", "Manager"]
    assert all("Only one reviewer" in prompt for prompt in world.stage.turn_prompts()[before:])
    # Nobody speaks again until the owner does.
    await world.room.advance(meeting_id)
    assert len(world.stage.turn_prompts()) == before + 2


async def test_a_manager_mid_step_shows_waiting_with_the_reason(world: World) -> None:
    world.stage.busy[world.manager_id] = "finishing its current step"
    seen: list[tuple[int | None, str | None]] = []

    async def watch(request: object) -> None:
        meeting = await world.meeting(meeting_id)
        seen.append((meeting.waiting_agent_id, meeting.waiting_reason))

    world.stage.on_start.append(watch)
    meeting_id = await _room(world)

    await world.service.start(meeting_id)

    # The CEO's turn saw no wait; the manager's turn did.
    assert seen == [(None, None), (world.manager_id, "finishing its current step")]
    meeting = await world.meeting(meeting_id)
    assert (meeting.waiting_agent_id, meeting.waiting_reason) == (None, None)
    async with world.sessions() as db:
        minutes = await read_minutes(db, meeting_id)
    notes = [e.text for e in minutes.transcript if e.source is TranscriptSource.SYSTEM]
    assert notes == ["Waiting for Manager: finishing its current step."]


async def test_the_turn_cap_closes_the_room_with_minutes_and_counts_the_cost(
    world: World,
) -> None:
    world.stage.minutes.append(_minutes(world))
    world.room._settings = world.room._settings.model_copy(update={"decision_turn_cap": 3})
    meeting_id = await _room(world)
    await world.service.start(meeting_id)
    await add_owner_entry(world.sessions, world.clock, meeting_id=meeting_id, text="Go on.")

    await world.room.advance(meeting_id)

    meeting = await world.meeting(meeting_id)
    assert (meeting.status, meeting.end_reason) == (MeetingStatus.ENDED, "turn_cap")
    # Two opening turns and one more: the third was the last allowed. Then the minutes.
    assert len(world.stage.turn_prompts()) == 3
    assert len(world.stage.minutes_prompts()) == 1
    async with world.sessions() as db:
        cost = await meeting_cost_micros(db, meeting_id)
    assert cost == 4 * 12_500


async def test_closing_posts_decisions_and_waits_for_the_owner_to_confirm_actions(
    world: World,
) -> None:
    world.stage.minutes.append(_minutes(world))
    meeting_id = await _room(world)
    await world.service.start(meeting_id)

    meeting = await world.room.close(meeting_id)

    assert meeting.status is MeetingStatus.ENDED
    async with world.sessions() as db:
        minutes = await read_minutes(db, meeting_id)
        task = await db.get_one(Task, minutes.action_items[0].task_id)
        approvals = list(
            await db.scalars(select(Approval).where(Approval.type == "decision_action"))
        )
    assert [d.text for d in minutes.decisions] == ["One reviewer"]
    # The task exists, unassigned: nothing was woken, nothing runs on the room's authority.
    assert task.assignee_id is None
    assert [a.status for a in approvals] == [ApprovalStatus.PENDING]
    with pytest.raises(RoomClosedError):
        await world.room.close(meeting_id)


async def test_a_closed_room_takes_no_owner_entry(world: World) -> None:
    world.stage.minutes.append(_minutes(world))
    meeting_id = await _room(world)
    await world.service.start(meeting_id)
    await world.room.close(meeting_id)

    from labhq.meetings import MeetingClosedError

    with pytest.raises(MeetingClosedError):
        await add_owner_entry(world.sessions, world.clock, meeting_id=meeting_id, text="late")


async def test_each_action_item_waits_on_its_own_approval(world: World) -> None:
    world.stage.minutes.append(_minutes(world))
    meeting_id = await _room(world)
    await world.service.start(meeting_id)
    await world.room.close(meeting_id)

    async with world.sessions() as db:
        item = (await read_minutes(db, meeting_id)).action_items[0]
        stored = await db.get_one(MeetingActionItem, item.id)
        approval = await db.get_one(Approval, stored.approval_id)

    assert approval.payload["task_id"] == item.task_id
    # An agent's own confirmation never grants it.
    with pytest.raises(ConfirmationNotAllowedError):
        await world.approvals.approve(approval.id, decider="agent:4", confirmation="ceo")
