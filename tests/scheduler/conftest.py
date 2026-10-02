from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.adapters import AdapterRegistry, FakeAdapter, FakeScript, default_registry
from labhq.budgets import BudgetSettings
from labhq.clock import FakeClock
from labhq.db import create_engine, session_factory
from labhq.db.enums import AgentStatus
from labhq.db.models import Task
from labhq.runs import RunService
from labhq.scheduler import Scheduler, SchedulerSettings, run_service_launcher
from tests.db.factories import project_agent_task

SETTINGS = SchedulerSettings(
    default_concurrency=1,
    default_timeout_seconds=600,
    heartbeat_limit_seconds=300,
    stop_grace_seconds=30,
)


@dataclass
class Scripts:
    """Hands each new fake adapter the next queued script, or a fresh default one."""

    queued: list[FakeScript] = field(default_factory=list)
    used: list[FakeScript] = field(default_factory=list)

    def next(self) -> FakeAdapter:
        script = self.queued.pop(0) if self.queued else FakeScript()
        self.used.append(script)
        return FakeAdapter(script)

    def hold(self, count: int = 1) -> list[FakeScript]:
        """Queue scripts whose runs stay open until interrupted."""
        scripts = [FakeScript(wait_for_interrupt=True) for _ in range(count)]
        self.queued.extend(scripts)
        return scripts


@dataclass
class World:
    sessions: async_sessionmaker[AsyncSession]
    clock: FakeClock
    scripts: Scripts
    registry: AdapterRegistry
    scheduler: Scheduler
    project_id: int
    agent_id: int
    task_ids: list[int]


@pytest.fixture
async def sessions(database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(database_url)
    try:
        yield session_factory(engine)
    finally:
        await engine.dispose()


@pytest.fixture
async def world(sessions: async_sessionmaker[AsyncSession], clock: FakeClock) -> World:
    scripts = Scripts()
    registry = default_registry.copy()
    registry.register("fake", scripts.next, replace=True)
    async with sessions() as db:
        project, agent, task = await project_agent_task(db, clock)
        agent.status = AgentStatus.ACTIVE
        now = clock.now()
        second = Task(project_id=project.id, title="Second task", created_at=now, updated_at=now)
        db.add(second)
        await db.commit()
        task_ids = [task.id, second.id]
    service = RunService(sessions, clock=clock, registry=registry)
    scheduler = Scheduler(
        sessions,
        clock=clock,
        launcher=run_service_launcher(service),
        settings=SETTINGS,
        budget_settings=BudgetSettings(),
    )
    return World(sessions, clock, scripts, registry, scheduler, project.id, agent.id, task_ids)
