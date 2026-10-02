"""Atomic checkout and the concurrency gate: one conditional statement each."""

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.clock import FakeClock
from labhq.db.enums import RunStatus
from labhq.db.models import Run
from labhq.scheduler import checkout, release, reserve_run
from tests.scheduler.conftest import World
from tests.scheduler.helpers import task


async def _queued_run(world: World) -> int:
    async with world.sessions() as db:
        row = Run(
            agent_id=world.agent_id,
            task_id=world.task_ids[0],
            adapter="fake",
            status=RunStatus.QUEUED,
            created_at=world.clock.now(),
        )
        db.add(row)
        await db.commit()
        return row.id


async def _checkout_in_own_session(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock, task_id: int, run_id: int
) -> bool:
    async with sessions() as db:
        won = await checkout(db, task_id, run_id, clock.now())
        await db.commit()
        return won


async def test_two_concurrent_checkouts_of_one_task_exactly_one_succeeds(world: World) -> None:
    first, second = await _queued_run(world), await _queued_run(world)
    task_id = world.task_ids[0]

    results = await asyncio.gather(
        _checkout_in_own_session(world.sessions, world.clock, task_id, first),
        _checkout_in_own_session(world.sessions, world.clock, task_id, second),
    )

    assert sorted(results) == [False, True]
    winner = first if results[0] else second
    assert (await task(world)).checkout_run_id == winner


async def test_release_frees_only_the_holder_and_a_new_checkout_then_succeeds(
    world: World,
) -> None:
    holder, other = await _queued_run(world), await _queued_run(world)
    task_id = world.task_ids[0]
    async with world.sessions() as db:
        now = world.clock.now()
        assert await checkout(db, task_id, holder, now)
        assert not await release(db, task_id, other, now)
        assert not await checkout(db, task_id, other, now)
        assert await release(db, task_id, holder, now)
        assert await checkout(db, task_id, other, now)
        await db.commit()
    assert (await task(world)).checkout_run_id == other


async def test_reserve_run_stops_at_the_concurrency_limit(world: World) -> None:
    async with world.sessions() as db:
        now = world.clock.now()
        reserve = {
            "agent_id": world.agent_id,
            "task_id": None,
            "adapter": "fake",
            "concurrency": 2,
            "now": now,
        }
        first = await reserve_run(db, **reserve)
        second = await reserve_run(db, **reserve)
        third = await reserve_run(db, **reserve)
        assert first is not None and second is not None
        assert third is None
        # A finished run frees its slot.
        row = await db.get_one(Run, first)
        row.status = RunStatus.SUCCEEDED
        await db.flush()
        assert await reserve_run(db, **reserve) is not None
