"""Atomic checkout: one conditional UPDATE decides, even between racing transactions."""

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.clock import FakeClock
from labhq.db.models import Task
from labhq.scheduler import checkout, release
from tests.db.factories import project_agent_task, run_for


async def _two_runs(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock
) -> tuple[int, int, int]:
    async with sessions() as db:
        _, agent, task = await project_agent_task(db, clock)
        first, second = await run_for(db, clock, agent, task), await run_for(db, clock, agent, task)
        await db.commit()
        return task.id, first.id, second.id


async def _checkout_and_commit(
    sessions: async_sessionmaker[AsyncSession], task_id: int, run_id: int, gate: asyncio.Event
) -> bool:
    async with sessions() as db:
        await gate.wait()
        won = await checkout(db, task_id, run_id)
        await db.commit()
        return won


async def test_two_concurrent_checkouts_of_one_task_exactly_one_succeeds(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock
) -> None:
    task_id, first, second = await _two_runs(sessions, clock)
    gate = asyncio.Event()
    racers = [
        asyncio.create_task(_checkout_and_commit(sessions, task_id, run_id, gate))
        for run_id in (first, second)
    ]
    gate.set()
    results = await asyncio.gather(*racers)

    assert sorted(results) == [False, True]
    winner = (first, second)[results.index(True)]
    async with sessions() as db:
        task = await db.get_one(Task, task_id)
        assert task.checkout_run_id == winner


async def test_a_held_task_refuses_checkout_until_its_run_releases_it(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock
) -> None:
    task_id, first, second = await _two_runs(sessions, clock)
    async with sessions() as db:
        assert await checkout(db, task_id, first)
        assert not await checkout(db, task_id, second)
        # Only the holder can release: another run's release changes nothing.
        assert await release(db, second) == 0
        assert await release(db, first) == 1
        assert await checkout(db, task_id, second)
        await db.commit()
