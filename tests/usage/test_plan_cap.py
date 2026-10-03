"""labhq's share of a plan window: warn at 50%, no new run from 70% until the reset."""

from datetime import timedelta

from labhq.budgets import Decision
from labhq.db.enums import RunStatus, WakeupStatus
from labhq.scheduler import Outcome, Verdict
from labhq.usage import UsageSettings
from tests.scheduler.conftest import World
from tests.scheduler.helpers import get_run, on_task, runs, wakeups
from tests.usage.plan_world import add_reading, notifications, on_kind, plan_scheduler

KIND = {"agent": "fake-a"}


async def test_at_the_warning_share_the_owner_is_warned_and_the_run_starts(world: World) -> None:
    scheduler = await on_kind(world, KIND)
    await add_reading(world, "fake-a", 55, resets_at=world.clock.now() + timedelta(hours=2))

    result = await scheduler.enqueue(on_task(world, "assign"))
    report = await scheduler.tick()
    await scheduler.settle()

    assert result.plan is not None and result.plan.decision is Decision.WARN
    assert len(report.started) == 1
    (warning,) = await notifications(world)
    assert "55%" in warning.title
    assert "used 55%" in warning.body


async def test_at_the_stop_share_no_run_starts_and_the_work_waits(world: World) -> None:
    scheduler = await on_kind(world, KIND)
    resets_at = world.clock.now() + timedelta(hours=2)
    await add_reading(world, "fake-a", 70, resets_at=resets_at)

    result = await scheduler.enqueue(on_task(world, "assign"))
    report = await scheduler.tick()

    assert result.outcome is Outcome.CREATED
    assert result.plan is not None and result.plan.resumes_at == resets_at
    assert report.started == []
    assert list(report.waiting.values()) == [Verdict.PLAN_PAUSED]
    assert [row.status for row in await wakeups(world)] == [WakeupStatus.PENDING]
    assert ["No new fake-a runs start" in n.body for n in await notifications(world)] == [True]


async def test_the_paused_work_starts_after_the_windows_reset(world: World) -> None:
    scheduler = await on_kind(world, KIND)
    await add_reading(world, "fake-a", 90, resets_at=world.clock.now() + timedelta(hours=2))
    await scheduler.enqueue(on_task(world, "assign"))
    assert (await scheduler.tick()).started == []

    world.clock.advance(timedelta(hours=2, seconds=1))
    report = await scheduler.tick()
    await scheduler.settle()

    assert len(report.started) == 1
    assert (await get_run(world, report.started[0])).status is RunStatus.SUCCEEDED


async def test_a_running_turn_is_not_cut_when_the_share_is_crossed(world: World) -> None:
    scheduler = await on_kind(world, KIND)
    world.fake.wait_for_interrupt = True
    await scheduler.enqueue(on_task(world, "assign"))
    (run_id,) = (await scheduler.tick()).started

    await add_reading(world, "fake-a", 95, resets_at=world.clock.now() + timedelta(hours=1))
    await scheduler.tick()

    assert world.fake.interrupts == 0
    assert scheduler.live_run_ids == [run_id]
    assert (await get_run(world, run_id)).status is RunStatus.RUNNING
    await scheduler.shutdown()


async def test_the_latest_valid_reading_of_a_window_stands(world: World) -> None:
    scheduler = await on_kind(world, KIND)
    resets_at = world.clock.now() + timedelta(hours=3)
    await add_reading(world, "fake-a", 80, resets_at=resets_at)
    world.clock.advance(60)
    # A failed reading is no reading: it does not lower the window to zero.
    await add_reading(world, "fake-a", None, error="extraction failed")

    await scheduler.enqueue(on_task(world, "assign"))
    assert (await scheduler.tick()).started == []

    world.clock.advance(60)
    await add_reading(world, "fake-a", 20, resets_at=resets_at)
    report = await scheduler.tick()
    await scheduler.settle()
    assert len(report.started) == 1


async def test_any_window_past_the_share_stops_the_kind(world: World) -> None:
    scheduler = await on_kind(world, KIND)
    later = world.clock.now() + timedelta(days=3)
    await add_reading(world, "fake-a", 10, resets_at=later)
    await add_reading(world, "fake-a", 75, window="seven_day", resets_at=later)

    await scheduler.enqueue(on_task(world, "assign"))

    assert (await scheduler.tick()).started == []


async def test_readings_of_another_kind_do_not_stop_this_one(world: World) -> None:
    scheduler = await on_kind(world, KIND)
    await add_reading(world, "fake-b", 99, resets_at=world.clock.now() + timedelta(hours=1))

    await scheduler.enqueue(on_task(world, "assign"))
    report = await scheduler.tick()
    await scheduler.settle()

    assert len(report.started) == 1
    assert await notifications(world) == []


async def test_both_thresholds_are_settings(world: World) -> None:
    await on_kind(world, KIND)
    scheduler = plan_scheduler(
        world, UsageSettings(plan_usage_warn_percent=60, plan_usage_stop_percent=90)
    )
    await add_reading(world, "fake-a", 80, resets_at=world.clock.now() + timedelta(hours=1))

    result = await scheduler.enqueue(on_task(world, "assign"))
    report = await scheduler.tick()
    await scheduler.settle()

    assert result.plan is not None and result.plan.decision is Decision.WARN
    assert len(report.started) == 1
    assert len(await runs(world)) == 1


async def test_other_adapters_are_their_own_kind(world: World) -> None:
    # The world's agent stays on the plain fake adapter: its kind is the adapter key.
    scheduler = plan_scheduler(world)
    await add_reading(world, "fake", 99, resets_at=world.clock.now() + timedelta(hours=1))

    await scheduler.enqueue(on_task(world, "assign"))

    assert (await scheduler.tick()).started == []
