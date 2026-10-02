from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.adapters import AdapterRegistry, FakeAdapter, FakeScript, default_registry
from labhq.clock import FakeClock
from labhq.db import create_engine, session_factory
from labhq.runs import RunService
from tests.adapters.stub_sdk import StubScript, stub_claude
from tests.db.factories import project_agent_task


class TickingClock(FakeClock):
    """Moves one second on every read, so each recorded instant is distinct."""

    def now(self) -> datetime:
        return self.advance(timedelta(seconds=1))


@dataclass
class World:
    service: RunService
    sessions: async_sessionmaker[AsyncSession]
    clock: TickingClock
    registry: AdapterRegistry
    fake: FakeScript
    claude: StubScript
    project_id: int
    agent_id: int
    task_id: int


@pytest.fixture
async def sessions(database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(database_url)
    try:
        yield session_factory(engine)
    finally:
        await engine.dispose()


@pytest.fixture
async def world(sessions: async_sessionmaker[AsyncSession], clock: FakeClock) -> World:
    ticking = TickingClock(clock.now())
    fake, claude = FakeScript(), StubScript()
    registry = default_registry.copy()
    registry.register("fake", lambda: FakeAdapter(fake), replace=True)
    registry.register("claude", stub_claude(claude), replace=True)
    async with sessions() as db:
        project, agent, task = await project_agent_task(db, ticking)
        await db.commit()
    return World(
        service=RunService(sessions, clock=ticking, registry=registry),
        sessions=sessions,
        clock=ticking,
        registry=registry,
        fake=fake,
        claude=claude,
        project_id=project.id,
        agent_id=agent.id,
        task_id=task.id,
    )
