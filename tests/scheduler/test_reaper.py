"""The reaper closes runs nobody owns any more, on the fake clock, and frees their tasks."""

from datetime import timedelta

from labhq.db.enums import RunStatus
from labhq.db.models import Run
from labhq.scheduler import checkout
from tests.scheduler.conftest import SETTINGS, World
from tests.scheduler.helpers import get_run, get_task, on_task

LIMIT = timedelta(seconds=SETTINGS.heartbeat_limit_seconds)


async def _killed_run(world: World) -> int:
    """A run started by a scheduler that then died with it: running, holding its task."""
    world.fake.wait_for_interrupt = True
    owner = world.fresh_scheduler()
    await owner.enqueue(on_task(world, "assign"))
    (run_id,) = (await owner.tick()).started
    # The owner is gone: nothing beats this run's heartbeat or waits on it any more.
    await owner.shutdown()
    async with world.sessions() as db:
        run = await db.get_one(Run, run_id)
        run.status, run.finished_at, run.exit = RunStatus.RUNNING, None, None
        assert await checkout(db, world.task_id, run_id)
        await db.commit()
    return run_id


async def test_a_killed_run_is_closed_by_the_reaper_and_its_checkout_released(
    world: World,
) -> None:
    run_id = await _killed_run(world)

    world.clock.advance(LIMIT)
    assert (await world.scheduler.tick()).reaped == []
    assert (await get_run(world, run_id)).status is RunStatus.RUNNING

    world.clock.advance(timedelta(seconds=1))
    report = await world.scheduler.tick()

    assert report.reaped == [run_id]
    run = await get_run(world, run_id)
    assert run.status is RunStatus.FAILED
    assert run.finished_at == world.clock.now()
    assert run.exit is not None and run.exit["error"] == "stale_heartbeat"
    assert (await get_task(world, world.task_id)).checkout_run_id is None


async def test_the_freed_task_can_be_taken_by_the_next_wakeup(world: World) -> None:
    await _killed_run(world)
    world.fake.wait_for_interrupt = False
    await world.scheduler.enqueue(on_task(world, "again"))
    world.clock.advance(LIMIT + timedelta(seconds=1))
    report = await world.scheduler.tick()
    assert len(report.reaped) == 1
    assert len(report.started) == 1


async def test_a_live_run_is_kept_alive_by_its_scheduler(world: World) -> None:
    world.fake.wait_for_interrupt = True
    await world.scheduler.enqueue(on_task(world, "assign"))
    (run_id,) = (await world.scheduler.tick()).started
    for _ in range(5):
        world.clock.advance(LIMIT - timedelta(seconds=1))
        assert (await world.scheduler.tick()).reaped == []
    assert (await get_run(world, run_id)).status is RunStatus.RUNNING


async def test_a_run_queued_but_never_started_is_reaped(world: World) -> None:
    async with world.sessions() as db:
        run = Run(
            agent_id=world.agent_id,
            task_id=world.task_id,
            adapter="fake",
            created_at=world.clock.now(),
        )
        db.add(run)
        await db.flush()
        assert await checkout(db, world.task_id, run.id)
        await db.commit()
    world.clock.advance(LIMIT + timedelta(seconds=1))
    assert (await world.scheduler.tick()).reaped == [run.id]
    assert (await get_task(world, world.task_id)).checkout_run_id is None


async def test_finished_runs_are_never_reaped(world: World) -> None:
    await world.scheduler.enqueue(on_task(world, "assign"))
    (run_id,) = (await world.scheduler.tick()).started
    await world.scheduler.settle()
    world.clock.advance(LIMIT * 10)
    assert (await world.scheduler.tick()).reaped == []
    assert (await get_run(world, run_id)).status is RunStatus.SUCCEEDED
