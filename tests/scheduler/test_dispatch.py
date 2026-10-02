"""Dispatch: concurrency per agent, the budget before start, approval and busy tasks."""

from sqlalchemy import select

from labhq.budgets import BudgetSettings
from labhq.db.enums import AgentStatus, RunStatus, WakeupStatus
from labhq.db.models import BudgetWarning, WakeupRequest
from labhq.runs import RunService
from labhq.scheduler import LaunchSpec, Scheduler, run_service_launcher
from tests.scheduler.conftest import SETTINGS, World
from tests.scheduler.helpers import configure_agent, requests, run, runs, spec, spend, task


async def _finish(world: World, run_id: int) -> None:
    handle = world.scheduler.handles[run_id]
    await handle.launched.interrupt()
    assert handle.driver is not None
    await handle.driver


async def test_with_concurrency_1_a_second_run_of_the_agent_waits(world: World) -> None:
    world.scripts.hold(2)
    await world.scheduler.enqueue(spec(world, "a", task=0))
    await world.scheduler.enqueue(spec(world, "b", task=1))

    (first,) = await world.scheduler.dispatch()

    assert (await task(world, 0)).checkout_run_id == first
    statuses = [row.status for row in await requests(world)]
    assert statuses == [WakeupStatus.DISPATCHED, WakeupStatus.PENDING]
    assert await world.scheduler.dispatch() == []
    assert len(await runs(world)) == 1

    await _finish(world, first)
    (second,) = await world.scheduler.dispatch()

    assert (await task(world, 0)).checkout_run_id is None
    assert (await task(world, 1)).checkout_run_id == second
    await _finish(world, second)


async def test_concurrency_comes_from_the_agent_config(world: World) -> None:
    world.scripts.hold(2)
    await configure_agent(world, config={"concurrency": 2})
    await world.scheduler.enqueue(spec(world, "a", task=0))
    await world.scheduler.enqueue(spec(world, "b", task=1))

    started = await world.scheduler.dispatch()

    assert len(started) == 2
    for run_id in started:
        await _finish(world, run_id)


async def test_a_finished_run_releases_its_checkout(world: World) -> None:
    await world.scheduler.enqueue(spec(world, "a"))
    (run_id,) = await world.scheduler.dispatch()
    await world.scheduler.drain()

    assert (await run(world, run_id)).status is RunStatus.SUCCEEDED
    assert (await task(world)).checkout_run_id is None
    assert world.scheduler.handles == {}


async def test_at_100_percent_no_new_run_starts_even_for_a_request_already_queued(
    world: World,
) -> None:
    await configure_agent(world, budget_micros=1_000_000)
    await world.scheduler.enqueue(spec(world, "a"))
    await spend(world, 1_000_000)

    assert await world.scheduler.dispatch() == []

    assert await runs(world) == []
    assert [row.status for row in await requests(world)] == [WakeupStatus.REFUSED]
    assert world.scripts.used == []


async def test_at_80_percent_the_run_starts_and_the_warning_is_recorded(world: World) -> None:
    await configure_agent(world, budget_micros=1_000_000)
    await world.scheduler.enqueue(spec(world, "a"))
    await spend(world, 850_000)

    (run_id,) = await world.scheduler.dispatch()
    await world.scheduler.drain()

    assert (await run(world, run_id)).status is RunStatus.SUCCEEDED
    async with world.sessions() as db:
        warnings = list(await db.scalars(select(BudgetWarning)))
    assert [(w.spent_micros, w.budget_micros) for w in warnings] == [(850_000, 1_000_000)]


async def test_an_agent_awaiting_approval_is_not_started(world: World) -> None:
    await configure_agent(world, status=AgentStatus.PENDING_APPROVAL)
    await world.scheduler.enqueue(spec(world, "a"))

    assert await world.scheduler.dispatch() == []
    assert [row.status for row in await requests(world)] == [WakeupStatus.PENDING]

    await configure_agent(world, status=AgentStatus.ACTIVE)
    assert len(await world.scheduler.dispatch()) == 1
    await world.scheduler.drain()


async def test_a_task_checked_out_by_another_run_waits_and_leaves_no_run_behind(
    world: World,
) -> None:
    world.scripts.hold()
    await configure_agent(world, config={"concurrency": 2})
    await world.scheduler.enqueue(spec(world, "a", task=0))
    (first,) = await world.scheduler.dispatch()
    # Dispatched work is no longer pending, so this one is new work for the busy task.
    await world.scheduler.enqueue(spec(world, "b", task=0))

    assert await world.scheduler.dispatch() == []

    # The agent had a free slot; the reservation was undone when the checkout failed.
    assert [row.id for row in await runs(world)] == [first]
    assert (await task(world)).checkout_run_id == first
    await _finish(world, first)
    (second,) = await world.scheduler.dispatch()
    assert (await task(world)).checkout_run_id == second
    await world.scheduler.drain()


async def test_a_launch_that_fails_closes_the_run_and_frees_the_task(world: World) -> None:
    async def broken(_request: WakeupRequest) -> LaunchSpec:
        raise RuntimeError("worktree could not be created")

    scheduler = Scheduler(
        world.sessions,
        clock=world.clock,
        launcher=run_service_launcher(RunService(world.sessions, clock=world.clock)),
        preparer=broken,
        settings=SETTINGS,
        budget_settings=BudgetSettings(),
    )
    await scheduler.enqueue(spec(world, "a"))

    (run_id,) = await scheduler.dispatch()

    failed = await run(world, run_id)
    assert failed.status is RunStatus.FAILED
    assert failed.exit == {"error": "RuntimeError", "message": "worktree could not be created"}
    assert (await task(world)).checkout_run_id is None
    assert scheduler.handles == {}
