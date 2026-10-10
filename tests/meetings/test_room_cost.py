"""A decision room's hard USD cap, its one-time overrun note and its equivalent-cost label."""

import pytest
from sqlalchemy import update

from labhq.db.enums import MeetingStatus, TranscriptSource
from labhq.db.models import Approval, CeoReport, Meeting, UsageReading
from labhq.meetings import (
    MeetingError,
    add_owner_entry,
    meeting_cost_micros,
    read_minutes,
)
from labhq.meetings.figures import room_figures
from tests.meetings.conftest import World

RUN_COST = 12_500


async def _room(world: World, **settings: int) -> int:
    world.service._settings = world.service._settings.model_copy(update=settings)
    async with world.sessions() as db:
        report = CeoReport(
            agent_id=world.ceo_id, text="Hire two reviewers.", refs=[], created_at=world.clock.now()
        )
        db.add(report)
        await db.commit()
        report_id = report.id
    meeting = await world.service.request(
        project_id=world.project_id,
        kind="decision",
        agenda="Should we hire?",
        requested_by=world.ceo_id,
        pinned=("report", report_id),
    )
    assert meeting.approval_id is not None
    await world.approvals.approve(meeting.approval_id, decider="owner", confirmation="tap")
    return meeting.id


async def _notes(world: World, meeting_id: int) -> list[str]:
    async with world.sessions() as db:
        minutes = await read_minutes(db, meeting_id)
    return [e.text for e in minutes.transcript if e.source is TranscriptSource.SYSTEM]


async def test_the_approval_card_carries_the_range_and_the_hard_cap(world: World) -> None:
    meeting_id = await _room(world, decision_cost_cap_micros=2_000_000)

    meeting = await world.meeting(meeting_id)
    async with world.sessions() as db:
        approval = await db.get_one(Approval, meeting.approval_id)
    assert (meeting.estimate_micros, meeting.estimate_high_micros) == (4_160_000, 8_320_000)
    assert (meeting.estimate_source, meeting.cost_cap_micros) == ("fallback", 2_000_000)
    assert approval.payload["estimate_micros"] == 4_160_000
    assert approval.payload["estimate_high_micros"] == 8_320_000
    assert approval.payload["estimate_source"] == "fallback"
    assert approval.payload["cost_cap_micros"] == 2_000_000


@pytest.mark.parametrize("missing", ["estimate_high_micros", "cost_cap_micros", "estimate_micros"])
async def test_a_room_without_its_range_or_cap_does_not_start(world: World, missing: str) -> None:
    meeting_id = await _room(world)
    async with world.sessions() as db:
        await db.execute(update(Meeting).where(Meeting.id == meeting_id).values({missing: None}))
        await db.commit()

    with pytest.raises(MeetingError, match="cost range and hard cap"):
        await world.service.start(meeting_id)

    assert (await world.meeting(meeting_id)).status is MeetingStatus.REQUESTED
    assert world.stage.prompts == []


async def test_the_room_stops_at_the_cap_says_why_and_still_writes_minutes(
    world: World,
) -> None:
    # Only the manager can take an action item: the CEO assigns no task of its own.
    world.stage.minutes.append(
        world.minutes_json().replace(str(world.lead_id), str(world.manager_id))
    )
    # Two opening turns cost 25,000: the cap is reached before anyone could answer again.
    meeting_id = await _room(world, decision_cost_cap_micros=2 * RUN_COST)

    await world.service.start(meeting_id)

    meeting = await world.meeting(meeting_id)
    assert (meeting.status, meeting.end_reason) == (MeetingStatus.ENDED, "cost_cap")
    assert len(world.stage.turn_prompts()) == 2
    assert len(world.stage.minutes_prompts()) == 1
    notes = await _notes(world, meeting_id)
    assert (
        notes[0]
        == "Cost cap reached ($0.0250 of $0.0250): the room stops and closes with its minutes."
    )
    async with world.sessions() as db:
        minutes = await read_minutes(db, meeting_id)
        cost = await meeting_cost_micros(db, meeting_id)
    assert [d.text for d in minutes.decisions] == ["Ship the parser first"]
    assert cost == 3 * RUN_COST


async def test_below_the_cap_the_room_keeps_going(world: World) -> None:
    meeting_id = await _room(world, decision_cost_cap_micros=2 * RUN_COST + 1)

    await world.service.start(meeting_id)

    assert (await world.meeting(meeting_id)).status is MeetingStatus.RUNNING


async def test_passing_the_high_estimate_is_announced_once(world: World) -> None:
    meeting_id = await _room(world)
    async with world.sessions() as db:
        await db.execute(
            update(Meeting).where(Meeting.id == meeting_id).values(estimate_high_micros=RUN_COST)
        )
        await db.commit()

    await world.service.start(meeting_id)
    await add_owner_entry(world.sessions, world.clock, meeting_id=meeting_id, text="And then?")
    await world.room.advance(meeting_id)

    over = [n for n in await _notes(world, meeting_id) if "above the high end" in n]
    assert over == ["The room has cost $0.0250, above the high end of its estimate ($0.0125)."]
    assert (await world.meeting(meeting_id)).over_estimate_at is not None


async def test_figures_label_subscription_runs_as_equivalent_cost(world: World) -> None:
    meeting_id = await _room(world)
    await world.service.start(meeting_id)
    async with world.sessions() as db:
        db.add(
            UsageReading(
                agent_id=world.ceo_id,
                agent_kind="fake",
                source="statusline",
                unit="percent",
                window="five_hour",
                value=41.0,
                created_at=world.clock.now(),
            )
        )
        await db.commit()
        meeting = await db.get_one(Meeting, meeting_id)
        settings = world.room._settings
        subscription = await room_figures(db, world.clock, meeting, settings, {})
        billed = await room_figures(db, world.clock, meeting, settings, {"ANTHROPIC_API_KEY": "x"})

    assert (subscription.equivalent_cost, subscription.plan_used_percent) == (True, 41.0)
    assert (billed.equivalent_cost, billed.plan_used_percent) == (False, None)
    assert subscription.spent_micros == billed.spent_micros == 2 * RUN_COST
    assert (subscription.turns, subscription.cap_micros) == (2, 5_000_000)
