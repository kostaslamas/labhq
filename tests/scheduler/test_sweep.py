"""Timeouts and the stale-run reaper, driven by the fake clock alone."""

import asyncio
from dataclasses import dataclass, field

from labhq.budgets import BudgetSettings
from labhq.db.enums import RunStatus
from labhq.db.models import Run
from labhq.scheduler import LaunchedRun, LaunchRequest, Scheduler, checkout
from tests.scheduler.conftest import SETTINGS, World
from tests.scheduler.helpers import configure_agent, run, spec, task


async def _orphan_run(world: World) -> int:
    """A running run nobody drives any more, as a killed worker or engine leaves it."""
    async with world.sessions() as db:
        now = world.clock.now()
        row = Run(
            agent_id=world.agent_id,
            task_id=world.task_ids[0],
            adapter="fake",
            status=RunStatus.RUNNING,
            created_at=now,
            started_at=now,
            heartbeat_at=now,
        )
        db.add(row)
        await db.flush()
        assert await checkout(db, world.task_ids[0], row.id, now)
        await db.commit()
        return row.id


async def test_a_killed_run_is_closed_by_the_reaper_and_its_checkout_released(
    world: World,
) -> None:
    run_id = await _orphan_run(world)

    world.clock.advance(SETTINGS.heartbeat_limit_seconds - 1)
    assert (await world.scheduler.sweep()).reaped == []
    world.clock.advance(2)
    report = await world.scheduler.sweep()

    assert report.reaped == [run_id]
    closed = await run(world, run_id)
    assert closed.status is RunStatus.FAILED
    assert closed.finished_at == world.clock.now()
    assert closed.exit is not None
    assert closed.exit["error"] == "stale_heartbeat"
    assert (await task(world)).checkout_run_id is None
    # The next wakeup for the task can check it out again.
    await world.scheduler.enqueue(spec(world, "after-reap"))
    assert len(await world.scheduler.dispatch()) == 1
    await world.scheduler.drain()


async def test_a_hung_run_of_this_scheduler_is_reaped_and_its_adapter_closed(
    world: World,
) -> None:
    (held,) = world.scripts.hold()
    await world.scheduler.enqueue(spec(world, "a"))
    (run_id,) = await world.scheduler.dispatch()

    world.clock.advance(SETTINGS.heartbeat_limit_seconds + 1)
    report = await world.scheduler.sweep()

    assert report.reaped == [run_id]
    assert (await run(world, run_id)).status is RunStatus.FAILED
    assert held.closes == 1
    assert world.scheduler.handles == {}
    assert (await task(world)).checkout_run_id is None


async def test_a_run_past_its_timeout_is_stopped_and_recorded_as_timed_out(
    world: World,
) -> None:
    (held,) = world.scripts.hold()
    await configure_agent(world, config={"timeout_seconds": 60})
    await world.scheduler.enqueue(spec(world, "a"))
    (run_id,) = await world.scheduler.dispatch()

    world.clock.advance(59)
    assert (await world.scheduler.sweep()).timed_out == []
    world.clock.advance(1)
    report = await world.scheduler.sweep()
    await world.scheduler.drain()

    assert report.timed_out == [run_id]
    assert held.interrupts == 1
    stopped = await run(world, run_id)
    assert stopped.status is RunStatus.TIMED_OUT
    assert stopped.exit is not None
    assert stopped.exit["timeout_seconds"] == 60
    assert stopped.exit["terminal_reason"] == "aborted_streaming"
    assert (await task(world)).checkout_run_id is None


@dataclass
class HungRun:
    """Ignores interrupts; only a forced stop ends it."""

    pid: int | None = 4242
    interrupts: int = 0
    _never: asyncio.Event = field(default_factory=asyncio.Event)

    async def wait(self) -> object:
        await self._never.wait()
        return None

    async def interrupt(self) -> None:
        self.interrupts += 1


@dataclass
class RecordingTerminator:
    killed: list[int] = field(default_factory=list)
    terminated: list[int] = field(default_factory=list)

    def terminate(self, pid: int) -> None:
        self.terminated.append(pid)

    def kill(self, pid: int) -> None:
        self.killed.append(pid)


async def test_an_unanswered_interrupt_is_followed_by_a_forced_stop_after_the_grace(
    world: World,
) -> None:
    hung, terminator = HungRun(), RecordingTerminator()
    # Below the heartbeat limit, so the timeout acts before the reaper would.
    await configure_agent(world, config={"timeout_seconds": 60})

    async def launch(request: LaunchRequest) -> LaunchedRun:
        async with world.sessions() as db:
            row = await db.get_one(Run, request.run_id)
            row.status, row.started_at = RunStatus.RUNNING, world.clock.now()
            await db.commit()
        return hung

    scheduler = Scheduler(
        world.sessions,
        clock=world.clock,
        launcher=launch,
        settings=SETTINGS,
        budget_settings=BudgetSettings(),
        terminator=terminator,
    )
    await scheduler.enqueue(spec(world, "a"))
    (run_id,) = await scheduler.dispatch()

    world.clock.advance(60)
    assert (await scheduler.sweep()).timed_out == [run_id]
    assert hung.interrupts == 1
    assert (await run(world, run_id)).status is RunStatus.RUNNING
    world.clock.advance(SETTINGS.stop_grace_seconds - 1)
    assert (await scheduler.sweep()).timed_out == []
    world.clock.advance(1)
    assert (await scheduler.sweep()).timed_out == [run_id]

    assert terminator.killed == [4242]
    stopped = await run(world, run_id)
    assert stopped.status is RunStatus.TIMED_OUT
    assert stopped.exit is not None
    assert stopped.exit["error"] == "timeout"
    assert (await task(world)).checkout_run_id is None
    assert scheduler.handles == {}


async def test_a_run_nobody_drives_is_timed_out_directly(world: World) -> None:
    run_id = await _orphan_run(world)
    world.clock.advance(SETTINGS.default_timeout_seconds)
    async with world.sessions() as db:
        # Keep it fresh so only the timeout applies.
        row = await db.get_one(Run, run_id)
        row.heartbeat_at = world.clock.now()
        await db.commit()

    report = await world.scheduler.sweep()

    assert report.timed_out == [run_id]
    assert report.reaped == []
    assert (await run(world, run_id)).status is RunStatus.TIMED_OUT
    assert (await task(world)).checkout_run_id is None
