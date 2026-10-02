"""Reads and small edits the run tests share."""

from typing import Any

from sqlalchemy import select, update

from labhq.db.models import Agent, AgentTaskSession, CostEvent, Run, RunEvent
from tests.runs.conftest import World


async def use_adapter(world: World, key: str, config: dict[str, Any] | None = None) -> None:
    async with world.sessions() as db:
        await db.execute(
            update(Agent).where(Agent.id == world.agent_id).values(adapter=key, config=config or {})
        )
        await db.commit()


async def stored_run(world: World, run_id: int) -> Run:
    async with world.sessions() as db:
        return await db.get_one(Run, run_id)


async def events_of(world: World, run_id: int) -> list[RunEvent]:
    async with world.sessions() as db:
        rows = await db.scalars(select(RunEvent).where(RunEvent.run_id == run_id))
        return sorted(rows, key=lambda row: row.seq)


async def costs_of(world: World, run_id: int) -> list[CostEvent]:
    async with world.sessions() as db:
        return list(await db.scalars(select(CostEvent).where(CostEvent.run_id == run_id)))


async def task_sessions(world: World) -> list[AgentTaskSession]:
    async with world.sessions() as db:
        return list(await db.scalars(select(AgentTaskSession)))
