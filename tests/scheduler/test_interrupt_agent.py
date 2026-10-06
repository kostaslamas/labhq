"""The scheduler interrupts the live runs it holds for an agent."""

from labhq.db.enums import RunStatus
from tests.scheduler.conftest import World
from tests.scheduler.helpers import get_run, on_task


async def test_interrupt_agent_stops_its_live_run_as_interrupted(world: World) -> None:
    world.fake.wait_for_interrupt = True
    await world.scheduler.enqueue(on_task(world, "assign"))
    (run_id,) = (await world.scheduler.tick()).started

    stopped = await world.scheduler.interrupt_agent(world.agent_id)
    await world.scheduler.settle()

    assert stopped is True
    assert world.fake.interrupts == 1
    assert (await get_run(world, run_id)).status is RunStatus.INTERRUPTED


async def test_interrupt_agent_without_a_live_run_reports_nothing_stopped(world: World) -> None:
    assert await world.scheduler.interrupt_agent(world.agent_id) is False
    assert world.fake.interrupts == 0
