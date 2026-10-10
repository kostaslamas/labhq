"""A room's action item runs only once the owner approved it, and only for a person's approval."""

from sqlalchemy import select

from labhq.approvals import (
    ApprovalService,
    default_actions,
    default_confirmations,
    default_executors,
)
from labhq.db.enums import ApprovalStatus, WakeupSource
from labhq.db.models import Approval, MeetingActionItem, Task, WakeupRequest
from labhq.hierarchy.executors import EngineAccess
from labhq.meetings.actions import DECISION_ACTION, decision_executor
from tests.meetings.conftest import World
from tests.meetings.test_room import _minutes, _room


async def _closed_room(world: World) -> int:
    world.stage.minutes.append(_minutes(world))
    meeting_id = await _room(world)
    await world.service.start(meeting_id)
    await world.room.close(meeting_id)
    async with world.sessions() as db:
        item = await db.scalar(select(MeetingActionItem))
        assert item is not None and item.approval_id is not None
        return item.approval_id


async def test_the_owner_approval_assigns_the_task_and_wakes_its_assignee(
    world: World, database_url: str
) -> None:
    approval_id = await _closed_room(world)
    executors = default_executors.copy()
    access = EngineAccess(database_url=lambda: database_url, clock=world.clock)
    executors.register(DECISION_ACTION, decision_executor(access), replace=True)
    approvals = ApprovalService(
        world.sessions,
        clock=world.clock,
        actions=default_actions.copy(),
        executors=executors,
        confirmations=default_confirmations.copy(),
    )

    done = await approvals.approve(approval_id, decider="web:owner", confirmation="tap")

    assert done.status is ApprovalStatus.EXECUTED
    async with world.sessions() as db:
        task = await db.scalar(select(Task))
        wakeup = await db.scalar(
            select(WakeupRequest).where(WakeupRequest.source == WakeupSource.ASSIGNMENT)
        )
        approval = await db.get_one(Approval, approval_id)
    assert task is not None and task.assignee_id == world.manager_id
    assert wakeup is not None and wakeup.agent_id == world.manager_id
    assert approval.confirmation_kind == "tap"


async def test_a_rejected_item_leaves_its_task_unassigned(world: World) -> None:
    approval_id = await _closed_room(world)

    await world.approvals.reject(approval_id, decider="web:owner", confirmation="tap")

    async with world.sessions() as db:
        task = await db.scalar(select(Task))
        wakeups = list(
            await db.scalars(
                select(WakeupRequest).where(WakeupRequest.source == WakeupSource.ASSIGNMENT)
            )
        )
    assert task is not None and task.assignee_id is None
    assert wakeups == []
