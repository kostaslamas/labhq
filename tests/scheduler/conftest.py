from collections.abc import AsyncIterator
from dataclasses import dataclass

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
)
BUDGETS = BudgetSettings()


@dataclass
class World:
    scheduler: Scheduler
    sessions: async_sessionmaker[AsyncSession]
    clock: FakeClock
    registry: AdapterRegistry
    fake: FakeScript
    project_id: int
    agent_id: int
    task_id: int

    def fresh_scheduler(self) -> Scheduler:
        """A second scheduler on the same database, as after a restart."""
        return build_scheduler(self.sessions, self.clock, self.registry)


def build_scheduler(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock, registry: AdapterRegistry
) -> Scheduler:
    return Scheduler(
        sessions,
        clock=clock,
        runs=RunService(sessions, clock=clock, registry=registry),
        settings=SETTINGS,
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
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock
) -> AsyncIterator[World]:
    fake = FakeScript()
    registry = default_registry.copy()
    registry.register("fake", lambda: FakeAdapter(fake), replace=True)
    async with sessions() as db:
        project, agent, task = await project_agent_task(db, clock)
        agent.status = AgentStatus.ACTIVE
        await db.commit()
    scheduler = build_scheduler(sessions, clock, registry)
    yield World(
        scheduler=scheduler,
        sessions=sessions,
        clock=clock,
        registry=registry,
        fake=fake,
        project_id=project.id,
        agent_id=agent.id,
        task_id=task.id,
    )
    # A test that leaves a run live must not leak its task into the next test.
    await scheduler.shutdown()
