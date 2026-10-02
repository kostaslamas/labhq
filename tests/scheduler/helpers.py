"""Reads and small edits the scheduler tests share."""

from typing import Any

from sqlalchemy import select, update

from labhq.db.enums import WakeupSource
from labhq.db.models import Agent, CostEvent, Run, Task, WakeupRequest
from labhq.scheduler import WakeupSpec
from tests.scheduler.conftest import World


def spec(
    world: World, key: str, *, task: int | None = 0, agent_id: int | None = None
) -> WakeupSpec:
    """A comment wakeup for the world's agent; `task` indexes `world.task_ids`."""
    return WakeupSpec(
        agent_id=agent_id or world.agent_id,
        task_id=None if task is None else world.task_ids[task],
        source=WakeupSource.COMMENT,
        reason="test",
        idempotency_key=key,
    )


async def requests(world: World) -> list[WakeupRequest]:
    async with world.sessions() as db:
        return list(await db.scalars(select(WakeupRequest).order_by(WakeupRequest.id)))


async def runs(world: World) -> list[Run]:
    async with world.sessions() as db:
        return list(await db.scalars(select(Run).order_by(Run.id)))


async def run(world: World, run_id: int) -> Run:
    async with world.sessions() as db:
        return await db.get_one(Run, run_id)


async def task(world: World, index: int = 0) -> Task:
    async with world.sessions() as db:
        return await db.get_one(Task, world.task_ids[index])


async def configure_agent(world: World, **values: Any) -> None:
    async with world.sessions() as db:
        await db.execute(update(Agent).where(Agent.id == world.agent_id).values(**values))
        await db.commit()


async def spend(world: World, micros: int) -> None:
    async with world.sessions() as db:
        db.add(
            CostEvent(
                agent_id=world.agent_id,
                project_id=world.project_id,
                cost_micros=micros,
                created_at=world.clock.now(),
            )
        )
        await db.commit()
