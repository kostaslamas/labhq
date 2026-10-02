"""Rows and reads the scheduler tests share."""

from typing import Any

from sqlalchemy import select, update

from labhq.adapters import FakeAdapter
from labhq.db.enums import WakeupSource
from labhq.db.models import Agent, Run, Task, WakeupRequest
from labhq.scheduler import Wakeup
from tests.scheduler.conftest import World


def on_task(
    world: World,
    key: str,
    *,
    task_id: int | None = None,
    source: WakeupSource = WakeupSource.ASSIGNMENT,
    reason: str = "",
) -> Wakeup:
    """A wakeup about a task, the world's own unless `task_id` names another."""
    return Wakeup(
        agent_id=world.agent_id,
        source=source,
        idempotency_key=key,
        task_id=task_id if task_id is not None else world.task_id,
        reason=reason,
    )


async def add_task(world: World, title: str, *, priority: int = 0) -> int:
    async with world.sessions() as db:
        now = world.clock.now()
        task = Task(
            project_id=world.project_id,
            title=title,
            priority=priority,
            created_at=now,
            updated_at=now,
        )
        db.add(task)
        await db.commit()
        return task.id


async def set_agent(world: World, **values: Any) -> None:
    async with world.sessions() as db:
        await db.execute(update(Agent).where(Agent.id == world.agent_id).values(**values))
        await db.commit()


async def get_run(world: World, run_id: int) -> Run:
    async with world.sessions() as db:
        return await db.get_one(Run, run_id)


async def get_task(world: World, task_id: int) -> Task:
    async with world.sessions() as db:
        return await db.get_one(Task, task_id)


async def wakeups(world: World) -> list[WakeupRequest]:
    async with world.sessions() as db:
        return list(await db.scalars(select(WakeupRequest).order_by(WakeupRequest.id)))


async def runs(world: World) -> list[Run]:
    async with world.sessions() as db:
        return list(await db.scalars(select(Run).order_by(Run.id)))


class DeafAdapter(FakeAdapter):
    """Counts interrupts but never acts on them, like a wedged agent process."""

    async def interrupt(self) -> None:
        self.script.interrupts += 1
