from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.clock import FakeClock
from labhq.db import create_engine, session_factory
from labhq.db.models import Agent
from tests.db.factories import project_agent_task


@dataclass
class Team:
    project_id: int
    manager_id: int
    worker_id: int
    task_id: int


@pytest.fixture
async def sessions(database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(database_url)
    try:
        yield session_factory(engine)
    finally:
        await engine.dispose()


@pytest.fixture
async def team(sessions: async_sessionmaker[AsyncSession], clock: FakeClock) -> Team:
    """A project with a manager and a worker reporting to it."""
    async with sessions() as db:
        project, worker, task = await project_agent_task(db, clock)
        now = clock.now()
        manager = Agent(
            project_id=project.id,
            role="manager",
            title="Manager",
            adapter="fake",
            created_at=now,
            updated_at=now,
        )
        db.add(manager)
        await db.flush()
        worker.reports_to = manager.id
        await db.commit()
        return Team(project.id, manager.id, worker.id, task.id)
