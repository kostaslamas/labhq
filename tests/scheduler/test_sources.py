"""The five wakeup sources and their registry."""

from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.db.enums import ApprovalStatus, RiskClass, WakeupSource
from labhq.db.models import Agent, Approval, Comment, Task
from labhq.scheduler import (
    ApprovalResolvedWakeup,
    AssignmentWakeup,
    CommentWakeup,
    EnqueueOutcome,
    MeetingWakeup,
    TimerWakeup,
    UnknownWakeupSourceError,
    WakeupSources,
    WakeupSpec,
    default_sources,
)
from tests.scheduler.conftest import World


async def _second_agent(world: World) -> int:
    async with world.sessions() as db:
        now = world.clock.now()
        agent = Agent(
            project_id=world.project_id,
            role="manager",
            title="Manager",
            adapter="fake",
            created_at=now,
            updated_at=now,
        )
        db.add(agent)
        await db.commit()
        return agent.id


async def _specs(world: World, trigger: object) -> list[WakeupSpec]:
    async with world.sessions() as db:
        return await default_sources.specs_for(db, trigger)  # type: ignore[arg-type]


def test_every_plan_source_has_a_handler() -> None:
    assert set(default_sources.sources()) == set(WakeupSource)


async def test_a_repeated_timer_trigger_enqueues_once(world: World) -> None:
    due = world.clock.now()
    trigger = TimerWakeup(agent_id=world.agent_id, due_at=due)

    first = await world.scheduler.wake(trigger)
    again = await world.scheduler.wake(trigger)
    later = await world.scheduler.wake(TimerWakeup(world.agent_id, due + timedelta(hours=1)))

    assert [r.outcome for r in first + again] == [EnqueueOutcome.CREATED, EnqueueOutcome.DUPLICATE]
    # A later slot is new work, merged into the pending one for the same agent.
    assert [r.outcome for r in later] == [EnqueueOutcome.COALESCED]


async def test_assignment_wakes_the_assignee_and_nobody_without_one(world: World) -> None:
    trigger = AssignmentWakeup(task_id=world.task_ids[0])
    assert await _specs(world, trigger) == []

    async with world.sessions() as db:
        task = await db.get_one(Task, world.task_ids[0])
        task.assignee_id = world.agent_id
        await db.commit()
    (spec,) = await _specs(world, trigger)

    assert (spec.agent_id, spec.task_id, spec.source) == (
        world.agent_id,
        world.task_ids[0],
        WakeupSource.ASSIGNMENT,
    )
    assert spec.idempotency_key.startswith(f"assignment:task:{world.task_ids[0]}:")


async def test_a_comment_wakes_each_mentioned_agent_but_not_its_author(world: World) -> None:
    other = await _second_agent(world)
    async with world.sessions() as db:
        comment = Comment(
            task_id=world.task_ids[1],
            author_agent_id=other,
            body="@worker please look, @manager fyi",
            mentions=[world.agent_id, other, world.agent_id],
            created_at=world.clock.now(),
        )
        db.add(comment)
        await db.commit()

    specs = await _specs(world, CommentWakeup(comment.id))

    assert [(s.agent_id, s.task_id) for s in specs] == [(world.agent_id, world.task_ids[1])]
    assert specs[0].idempotency_key == f"comment:{comment.id}:agent:{world.agent_id}"


async def _approval(db: AsyncSession, world: World, status: ApprovalStatus) -> Approval:
    approval = Approval(
        type="push",
        risk_class=RiskClass.HEAVY,
        status=status,
        requested_by_agent_id=world.agent_id,
        task_id=world.task_ids[0],
        created_at=world.clock.now(),
    )
    db.add(approval)
    await db.commit()
    return approval


async def test_a_resolved_approval_wakes_its_requester_once_per_decision(world: World) -> None:
    async with world.sessions() as db:
        approval = await _approval(db, world, ApprovalStatus.PENDING)
    trigger = ApprovalResolvedWakeup(approval.id)
    assert await _specs(world, trigger) == []

    async with world.sessions() as db:
        row = await db.get_one(Approval, approval.id)
        row.status = ApprovalStatus.APPROVED
        await db.commit()
    (spec,) = await _specs(world, trigger)

    assert (spec.agent_id, spec.task_id) == (world.agent_id, world.task_ids[0])
    assert spec.idempotency_key == f"approval:{approval.id}:approved"


async def test_a_meeting_wakes_the_named_participant(world: World) -> None:
    (spec,) = await _specs(world, MeetingWakeup(world.agent_id, "standup-42"))

    assert spec.source is WakeupSource.MEETING
    assert spec.idempotency_key == f"meeting:standup-42:agent:{world.agent_id}"


async def test_a_new_source_handler_is_a_registration(world: World) -> None:
    sources = WakeupSources()

    async def meeting(_db: AsyncSession, trigger: MeetingWakeup) -> list[WakeupSpec]:
        return [WakeupSpec(trigger.agent_id, None, WakeupSource.MEETING, "custom", "k")]

    async with world.sessions() as db:
        with pytest.raises(UnknownWakeupSourceError):
            await sources.specs_for(db, MeetingWakeup(world.agent_id, "m"))
        sources.register(WakeupSource.MEETING, meeting)
        (spec,) = await sources.specs_for(db, MeetingWakeup(world.agent_id, "m"))
    assert spec.reason == "custom"
    with pytest.raises(ValueError, match="already registered"):
        sources.register(WakeupSource.MEETING, meeting)
    copy = default_sources.copy()
    copy.register(WakeupSource.MEETING, meeting, replace=True)
    assert default_sources.sources() == copy.sources()
