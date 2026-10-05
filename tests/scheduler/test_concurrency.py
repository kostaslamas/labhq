"""Concurrency per agent from `agents.config`, default 1; a waiting wakeup stays pending."""

from labhq.db.enums import AgentStatus, RunStatus, WakeupStatus
from labhq.scheduler import Verdict
from tests.scheduler.conftest import World
from tests.scheduler.helpers import add_task, get_run, get_task, on_task, set_agent, wakeups


async def _two_tasks_queued(world: World) -> int:
    other = await add_task(world, "Second task")
    await world.scheduler.enqueue(on_task(world, "first"))
    await world.scheduler.enqueue(on_task(world, "second", task_id=other))
    return other


async def test_with_concurrency_1_a_second_run_of_the_agent_waits(world: World) -> None:
    world.fake.wait_for_interrupt = True
    other = await _two_tasks_queued(world)

    report = await world.scheduler.tick()
    assert len(report.started) == 1
    assert list(report.waiting.values()) == [Verdict.AT_CONCURRENCY]
    statuses = [row.status for row in await wakeups(world)]
    assert statuses == [WakeupStatus.DISPATCHED, WakeupStatus.PENDING]
    assert (await get_task(world, other)).checkout_run_id is None

    await world.scheduler.shutdown()
    world.fake.wait_for_interrupt = False
    report = await world.scheduler.tick()
    (second,) = report.started
    assert (await get_run(world, second)).task_id == other


async def test_agent_config_raises_the_limit(world: World) -> None:
    world.fake.wait_for_interrupt = True
    await set_agent(world, config={"max_concurrency": 2})
    await _two_tasks_queued(world)
    report = await world.scheduler.tick()
    assert len(report.started) == 2
    assert report.waiting == {}


async def test_ceo_keeps_one_active_run_even_if_config_allows_two(world: World) -> None:
    world.fake.wait_for_interrupt = True
    await set_agent(world, role="ceo", config={"max_concurrency": 2})
    await _two_tasks_queued(world)

    report = await world.scheduler.tick()

    assert len(report.started) == 1
    assert list(report.waiting.values()) == [Verdict.AT_CONCURRENCY]


async def test_a_task_held_by_another_run_waits_even_below_the_limit(world: World) -> None:
    world.fake.wait_for_interrupt = True
    await set_agent(world, config={"max_concurrency": 2})
    await world.scheduler.enqueue(on_task(world, "first"))
    (first,) = (await world.scheduler.tick()).started
    await world.scheduler.enqueue(on_task(world, "again"))

    report = await world.scheduler.tick()
    assert report.started == []
    assert list(report.waiting.values()) == [Verdict.TASK_HELD]
    assert (await get_task(world, world.task_id)).checkout_run_id == first


async def test_an_agent_that_is_not_active_waits(world: World) -> None:
    await set_agent(world, status=AgentStatus.PAUSED)
    await world.scheduler.enqueue(on_task(world, "first"))
    report = await world.scheduler.tick()
    assert report.started == []
    assert list(report.waiting.values()) == [Verdict.AGENT_INACTIVE]


async def test_higher_priority_tasks_start_first(world: World) -> None:
    urgent = await add_task(world, "Urgent", priority=10)
    await world.scheduler.enqueue(on_task(world, "normal"))
    await world.scheduler.enqueue(on_task(world, "urgent", task_id=urgent))
    (run_id,) = (await world.scheduler.tick()).started
    assert (await get_run(world, run_id)).task_id == urgent


async def test_a_finished_run_releases_its_checkout(world: World) -> None:
    await world.scheduler.enqueue(on_task(world, "first"))
    (run_id,) = (await world.scheduler.tick()).started
    assert (await get_task(world, world.task_id)).checkout_run_id == run_id
    await world.scheduler.settle()
    assert (await get_run(world, run_id)).status is RunStatus.SUCCEEDED
    assert (await get_task(world, world.task_id)).checkout_run_id is None
