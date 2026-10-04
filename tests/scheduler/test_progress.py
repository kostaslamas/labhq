"""A run ending silently cannot strand an assigned task forever."""

from sqlalchemy import select

from labhq.db.enums import AgentStatus, RunStatus, TaskStatus, WakeupStatus
from labhq.db.models import Agent, Notification, Run, Task, WakeupRequest
from labhq.scheduler.progress import continue_task
from tests.scheduler.conftest import World
from tests.scheduler.helpers import get_task, on_task


async def test_unreported_task_retries_then_escalates_to_its_reviewer(world: World) -> None:
    async with world.sessions() as db:
        manager = Agent(
            project_id=world.project_id,
            role="manager",
            title="Manager",
            adapter="fake",
            status=AgentStatus.ACTIVE,
            created_at=world.clock.now(),
            updated_at=world.clock.now(),
        )
        db.add(manager)
        await db.flush()
        worker = await db.get_one(Agent, world.agent_id)
        worker.reports_to = manager.id
        task = await db.get_one(Task, world.task_id)
        task.assignee_id = worker.id
        await db.commit()

    await world.scheduler.enqueue(on_task(world, "initial"))
    for attempt in range(3):
        report = await world.scheduler.tick()
        assert len(report.started) == 1
        await world.scheduler.settle()
        task = await get_task(world, world.task_id)
        if attempt < 2:
            assert task.status is TaskStatus.IN_PROGRESS
        else:
            assert task.status is TaskStatus.BLOCKED

    async with world.sessions() as db:
        wakeups = list(await db.scalars(select(WakeupRequest).order_by(WakeupRequest.id)))
    assert any(
        w.agent_id == manager.id and w.task_id == world.task_id and w.status == WakeupStatus.PENDING
        for w in wakeups
    )


async def test_a_reviewer_who_ends_without_deciding_is_retried_then_escalated(world: World) -> None:
    async with world.sessions() as db:
        ceo = Agent(
            role="ceo",
            title="CEO",
            adapter="fake",
            status=AgentStatus.ACTIVE,
            created_at=world.clock.now(),
            updated_at=world.clock.now(),
        )
        db.add(ceo)
        await db.flush()
        manager = await db.get_one(Agent, world.agent_id)
        manager.role = "manager"
        manager.reports_to = ceo.id
        task = await db.get_one(Task, world.task_id)
        task.assignee_id = manager.id
        task.status = TaskStatus.IN_REVIEW
        run = Run(
            agent_id=ceo.id,
            task_id=task.id,
            adapter="fake",
            status=RunStatus.SUCCEEDED,
            created_at=world.clock.now(),
            started_at=world.clock.now(),
        )
        db.add(run)
        await db.flush()
        await continue_task(db, world.clock, run.id, max_unreported_runs=2)
        await db.commit()
    async with world.sessions() as db:
        wakeups = list(await db.scalars(select(WakeupRequest)))
    assert any(w.agent_id == ceo.id and w.task_id == world.task_id for w in wakeups)

    async with world.sessions() as db:
        for wakeup in await db.scalars(select(WakeupRequest)):
            wakeup.status = WakeupStatus.DISPATCHED
        second = Run(
            agent_id=ceo.id,
            task_id=world.task_id,
            adapter="fake",
            status=RunStatus.SUCCEEDED,
            created_at=world.clock.now(),
            started_at=world.clock.now(),
        )
        db.add(second)
        await db.flush()
        await continue_task(db, world.clock, second.id, max_unreported_runs=2)
        await db.commit()
    async with world.sessions() as db:
        notices = list(await db.scalars(select(Notification)))
    assert len(notices) == 1
