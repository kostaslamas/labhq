import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.adapters import AdapterRegistry, FakeAdapter, FakeScript, default_registry
from labhq.budgets import BudgetSettings
from labhq.clock import FakeClock
from labhq.db import create_engine, session_factory
from labhq.db.enums import AgentStatus
from labhq.runs import RunService
from labhq.scheduler import Scheduler, SchedulerSettings
from tests.db.factories import project_agent_task

SETTINGS = SchedulerSettings(
    default_concurrency=1,
    default_timeout_seconds=600,
    heartbeat_limit_seconds=120,
    interrupt_grace_seconds=30,
    tick_seconds=5,
    # The escalation tests need a small limit; production's default is higher.
    max_unreported_runs=3,
    # Fake agents never report, so the automatic next turn would start runs behind the tests'
    # backs (#150). Only the progress tests turn it on.
    auto_next_turn=False,
)
BUDGETS = BudgetSettings()


@dataclass
class World:
    scheduler: Scheduler
    sessions: async_sessionmaker[AsyncSession]
    clock: FakeClock
    registry: AdapterRegistry
    fake: FakeScript
    settings: SchedulerSettings
    project_id: int
    agent_id: int
    task_id: int
    schedulers: list[Scheduler] = field(default_factory=list)

    def fresh_scheduler(self) -> Scheduler:
        """A second scheduler on the same database, as after a restart."""
        scheduler = build_scheduler(self.sessions, self.clock, self.registry, self.settings)
        self.schedulers.append(scheduler)
        return scheduler


def build_scheduler(
    sessions: async_sessionmaker[AsyncSession],
    clock: FakeClock,
    registry: AdapterRegistry,
    settings: SchedulerSettings = SETTINGS,
) -> Scheduler:
    return Scheduler(
        sessions,
        clock=clock,
        runs=RunService(sessions, clock=clock, registry=registry),
        settings=settings,
        budget_settings=BUDGETS,
    )


@pytest.fixture
async def sessions(database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(database_url)
    try:
        yield session_factory(engine)
    finally:
        await engine.dispose()


@pytest.fixture
async def world(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock, auto_next_turn: bool
) -> AsyncIterator[World]:
    fake = FakeScript()
    registry = default_registry.copy()
    registry.register("fake", lambda: FakeAdapter(fake), replace=True)
    async with sessions() as db:
        project, agent, task = await project_agent_task(db, clock)
        agent.status = AgentStatus.ACTIVE
        await db.commit()
    settings = SETTINGS.model_copy(update={"auto_next_turn": auto_next_turn})
    scheduler = build_scheduler(sessions, clock, registry, settings)
    world = World(
        scheduler=scheduler,
        settings=settings,
        sessions=sessions,
        clock=clock,
        registry=registry,
        fake=fake,
        project_id=project.id,
        agent_id=agent.id,
        task_id=task.id,
        schedulers=[scheduler],
    )
    yield world
    # A test that leaves a run live must not leak it into the next test, or hang the loop's
    # teardown on a waiter nobody collects (#150).
    for owner in world.schedulers:
        await owner.shutdown()
    assert [owner.live_run_ids for owner in world.schedulers] == [[]] * len(world.schedulers)
    current = asyncio.current_task()
    pending = [task for task in asyncio.all_tasks() if task is not current and not task.done()]
    assert not pending, f"a scheduler test left tasks running: {pending}"
