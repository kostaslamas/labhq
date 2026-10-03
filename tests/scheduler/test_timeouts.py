"""A run past its timeout is interrupted and recorded as timed out; a deaf one is abandoned."""

from datetime import timedelta

from labhq.adapters import FakeScript
from labhq.db.enums import RunStatus
from tests.scheduler.conftest import SETTINGS, World
from tests.scheduler.helpers import DeafAdapter, get_run, get_task, on_task, set_agent

TIMEOUT = timedelta(seconds=SETTINGS.default_timeout_seconds)
GRACE = timedelta(seconds=SETTINGS.interrupt_grace_seconds)


async def _start(world: World) -> int:
    await world.scheduler.enqueue(on_task(world, "assign"))
    (run_id,) = (await world.scheduler.tick()).started
    return run_id


async def test_a_run_past_its_timeout_is_stopped_and_recorded_as_timed_out(world: World) -> None:
    world.fake.wait_for_interrupt = True
    run_id = await _start(world)

    world.clock.advance(TIMEOUT - timedelta(seconds=1))
    assert (await world.scheduler.tick()).timed_out == []
    world.clock.advance(timedelta(seconds=1))
    report = await world.scheduler.tick()
    assert report.timed_out == [run_id]
    assert world.fake.interrupts == 1

    await world.scheduler.settle()
    run = await get_run(world, run_id)
    assert run.status is RunStatus.TIMED_OUT
    assert run.exit is not None
    assert run.exit["stopped_by"] == "timeout"
    assert run.exit["terminal_reason"] == "aborted_streaming"
    assert run.exit["timeout_seconds"] == SETTINGS.default_timeout_seconds
    assert (await get_task(world, world.task_id)).checkout_run_id is None


async def test_the_timeout_comes_from_agents_config(world: World) -> None:
    world.fake.wait_for_interrupt = True
    await set_agent(world, config={"timeout_seconds": 60})
    run_id = await _start(world)
    world.clock.advance(timedelta(seconds=60))
    assert (await world.scheduler.tick()).timed_out == [run_id]


async def test_a_run_that_ignores_its_interrupt_is_abandoned_after_the_grace(
    world: World,
) -> None:
    script = FakeScript(wait_for_interrupt=True)
    world.registry.register("fake", lambda: DeafAdapter(script), replace=True)
    run_id = await _start(world)

    world.clock.advance(TIMEOUT)
    await world.scheduler.tick()
    world.clock.advance(GRACE - timedelta(seconds=1))
    assert (await world.scheduler.tick()).finished == []
    world.clock.advance(timedelta(seconds=1))
    report = await world.scheduler.tick()

    assert report.finished == [run_id]
    assert world.scheduler.live_run_ids == []
    assert script.interrupts == 1
    run = await get_run(world, run_id)
    assert run.status is RunStatus.TIMED_OUT
    assert run.finished_at == world.clock.now()
    assert (await get_task(world, world.task_id)).checkout_run_id is None


async def test_a_run_inside_its_timeout_is_left_alone(world: World) -> None:
    run_id = await _start(world)
    await world.scheduler.settle()
    assert (await get_run(world, run_id)).status is RunStatus.SUCCEEDED
    assert world.fake.interrupts == 0
