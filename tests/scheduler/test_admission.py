"""The global run cap, the free-memory floor and who starts first when the machine is full."""

from dataclasses import dataclass, field

import pytest
from sqlalchemy import select

from labhq.callcenter.answers.status import health
from labhq.db.enums import AgentStatus, WakeupSource, WakeupStatus
from labhq.db.models import Agent, Notification
from labhq.runs import RunService
from labhq.scheduler import Scheduler, SchedulerSettings, Verdict, Wakeup
from labhq.scheduler.memory import MemoryReading, default_max_running
from tests.scheduler.conftest import BUDGETS, SETTINGS, World
from tests.scheduler.helpers import add_task, get_run, on_task, wakeups

GIB = 1024**3


@dataclass
class Meter:
    """Memory readings a test sets; the real machine is never read."""

    total: int = 16 * GIB
    free_percent: float = 80.0
    reads: list[float] = field(default_factory=list)

    def __call__(self) -> MemoryReading:
        self.reads.append(self.free_percent)
        return MemoryReading(self.total, int(self.total * self.free_percent / 100))


def scheduler_with(world: World, meter: Meter, **limits: float) -> Scheduler:
    settings = SchedulerSettings(**{**SETTINGS.model_dump(), **limits})
    return Scheduler(
        world.sessions,
        clock=world.clock,
        runs=RunService(world.sessions, clock=world.clock, registry=world.registry),
        settings=settings,
        budget_settings=BUDGETS,
        memory=meter,
    )


async def add_agent(world: World, role: str) -> tuple[int, int]:
    """An active agent of `role` and a task of its own; returns (agent id, task id)."""
    async with world.sessions() as db:
        now = world.clock.now()
        template = await db.get_one(Agent, world.agent_id)
        agent = Agent(
            project_id=template.project_id,
            role=role,
            title=role,
            adapter="fake",
            status=AgentStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        db.add(agent)
        await db.commit()
    return agent.id, await add_task(world, f"{role} task")


def wake(
    agent_id: int,
    task_id: int | None,
    key: str,
    source: WakeupSource = WakeupSource.ASSIGNMENT,
) -> Wakeup:
    return Wakeup(agent_id=agent_id, source=source, idempotency_key=key, task_id=task_id)


async def test_with_the_cap_reached_a_new_wakeup_waits_and_starts_when_a_run_ends(
    world: World,
) -> None:
    world.fake.wait_for_interrupt = True
    scheduler = scheduler_with(world, Meter(), max_running=1)
    other_agent, other_task = await add_agent(world, "worker")
    await scheduler.enqueue(on_task(world, "first"))
    await scheduler.enqueue(wake(other_agent, other_task, "second"))

    report = await scheduler.tick()
    assert len(report.started) == 1
    assert list(report.waiting.values()) == [Verdict.AT_CAPACITY]

    world.clock.advance(60)
    assert (await scheduler.tick()).started == []

    await scheduler.shutdown()
    world.fake.wait_for_interrupt = False
    report = await scheduler.tick()
    (second,) = report.started
    assert (await get_run(world, second)).agent_id == other_agent
    await scheduler.shutdown()


async def test_below_the_free_memory_floor_nothing_starts_and_one_warning_is_recorded(
    world: World,
) -> None:
    meter = Meter(free_percent=10.0)
    scheduler = scheduler_with(world, meter, max_running=4)
    await scheduler.enqueue(on_task(world, "first"))

    for _ in range(3):
        report = await scheduler.tick()
        assert report.started == []
        assert list(report.waiting.values()) == [Verdict.LOW_MEMORY]
        world.clock.advance(5)

    assert [row.status for row in await wakeups(world)] == [WakeupStatus.PENDING]
    async with world.sessions() as db:
        notices = list(
            await db.scalars(select(Notification).where(Notification.kind == "server_memory"))
        )
    assert len(notices) == 1

    meter.free_percent = 40.0
    report = await scheduler.tick()
    assert len(report.started) == 1

    # A second episode is announced again.
    meter.free_percent = 5.0
    await scheduler.enqueue(on_task(world, "later"))
    world.clock.advance(60)
    await scheduler.tick()
    async with world.sessions() as db:
        notices = list(
            await db.scalars(select(Notification).where(Notification.kind == "server_memory"))
        )
    assert len(notices) == 2


async def test_the_floor_can_be_switched_off(world: World) -> None:
    scheduler = scheduler_with(world, Meter(free_percent=1.0), min_free_memory_percent=0)
    await scheduler.enqueue(on_task(world, "first"))
    assert len((await scheduler.tick()).started) == 1


async def test_when_capped_an_owner_message_to_the_ceo_starts_before_a_longer_waiting_worker(
    world: World,
) -> None:
    world.fake.wait_for_interrupt = True
    scheduler = scheduler_with(world, Meter(), max_running=1)
    ceo, _ = await add_agent(world, "ceo")
    await scheduler.enqueue(on_task(world, "worker-waited-longer"))
    world.clock.advance(3600)
    await scheduler.enqueue(wake(ceo, None, "owner", WakeupSource.OWNER_MESSAGE))

    (started,) = (await scheduler.tick()).started

    assert (await get_run(world, started)).agent_id == ceo
    await scheduler.shutdown()


async def test_groups_start_ceo_then_managers_then_workers(world: World) -> None:
    world.fake.wait_for_interrupt = True
    scheduler = scheduler_with(world, Meter(), max_running=2)
    manager, manager_task = await add_agent(world, "manager")
    ceo, _ = await add_agent(world, "ceo")
    await scheduler.enqueue(on_task(world, "worker"))
    await scheduler.enqueue(wake(manager, manager_task, "manager"))
    await scheduler.enqueue(wake(ceo, None, "ceo", WakeupSource.OWNER_MESSAGE))

    started = (await scheduler.tick()).started

    assert {(await get_run(world, run_id)).agent_id for run_id in started} == {ceo, manager}
    await scheduler.shutdown()


def test_the_default_cap_follows_the_machine_within_bounds() -> None:
    assert default_max_running(512 * 1024**2) == 1
    assert default_max_running(3 * GIB) == 2
    assert default_max_running(8 * GIB) == 5
    assert default_max_running(16 * GIB) == 8
    assert default_max_running(256 * GIB) == 8


async def test_an_unset_cap_is_derived_from_the_injected_total(world: World) -> None:
    world.fake.wait_for_interrupt = True
    scheduler = scheduler_with(world, Meter(total=2 * GIB))
    other_agent, other_task = await add_agent(world, "worker")
    await scheduler.enqueue(on_task(world, "first"))
    await scheduler.enqueue(wake(other_agent, other_task, "second"))

    report = await scheduler.tick()

    assert len(report.started) == 1
    assert list(report.waiting.values()) == [Verdict.AT_CAPACITY]
    await scheduler.shutdown()


async def test_the_status_answer_reports_running_cap_and_free_memory(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.fake.wait_for_interrupt = True
    meter = Meter(free_percent=62.0)
    scheduler = scheduler_with(world, meter, max_running=3)
    monkeypatch.setattr("labhq.scheduler.capacity.system_memory", meter)
    monkeypatch.setattr(
        "labhq.scheduler.capacity.get_scheduler_settings",
        lambda: SchedulerSettings(max_running=3),
    )
    await scheduler.enqueue(on_task(world, "first"))
    await scheduler.tick()

    async with world.sessions() as db:
        text = await health(db, world.clock)

    assert "One agent run active out of 3 allowed" in text
    assert "62 percent of memory is free" in text
    await scheduler.shutdown()


class RecordingPanes:
    def __init__(self) -> None:
        self.calls = 0

    async def suspend_idle(self) -> list[str]:
        self.calls += 1
        return ["ceo_claude"]


async def test_each_tick_asks_the_pane_suspender_and_reports_what_it_stopped(world: World) -> None:
    panes = RecordingPanes()
    scheduler = Scheduler(
        world.sessions,
        clock=world.clock,
        runs=RunService(world.sessions, clock=world.clock, registry=world.registry),
        settings=SETTINGS,
        panes=panes,
    )

    report = await scheduler.tick()

    assert panes.calls == 1
    assert report.suspended == ["ceo_claude"]
