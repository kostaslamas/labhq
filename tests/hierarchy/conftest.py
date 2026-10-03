from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.approvals import ApprovalService, default_actions, default_confirmations
from labhq.approvals.executors import Executor, default_executors
from labhq.approvals.registry import Registry
from labhq.clock import FakeClock
from labhq.db import create_engine, session_factory
from labhq.db.models import Agent, Project
from labhq.hierarchy import (
    CREATE_AGENT,
    CREATE_TEAM,
    EngineAccess,
    Hierarchy,
    HierarchySettings,
    agent_executor,
    team_executor,
)

ADAPTERS = frozenset({"fake"})
CAP = 3


@dataclass
class World:
    hierarchy: Hierarchy
    approvals: ApprovalService
    sessions: async_sessionmaker[AsyncSession]
    clock: FakeClock
    settings: HierarchySettings
    executors: Registry[Executor]
    project: str

    async def agents(self) -> list[Agent]:
        async with self.sessions() as db:
            return list(await db.scalars(select(Agent).order_by(Agent.id)))

    async def agent(self, agent_id: int) -> Agent:
        async with self.sessions() as db:
            return await db.get_one(Agent, agent_id)

    async def active_manager(self) -> Agent:
        assignment = await self.hierarchy.assign_manager(self.project)
        assert assignment.approval is not None
        await self.approvals.approve(assignment.approval.id, decider="operator", confirmation="cli")
        return await self.agent(assignment.manager.id)


@pytest.fixture
async def sessions(database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(database_url)
    try:
        yield session_factory(engine)
    finally:
        await engine.dispose()


@pytest.fixture
def settings() -> HierarchySettings:
    return HierarchySettings(approve_new_agents=True, max_team_size=CAP, org_adapter="fake")


@pytest.fixture
async def world(
    sessions: async_sessionmaker[AsyncSession],
    clock: FakeClock,
    database_url: str,
    settings: HierarchySettings,
) -> World:
    async with sessions() as db:
        now = clock.now()
        db.add(Project(name="site", repo_path="/srv/site", created_at=now, updated_at=now))
        await db.commit()
    # Executors bound to this test's database and clock, in copies of the registries.
    access = EngineAccess(database_url=lambda: database_url, clock=clock, settings=lambda: settings)
    executors = default_executors.copy()
    executors.register(CREATE_AGENT, agent_executor(access), replace=True)
    executors.register(CREATE_TEAM, team_executor(access), replace=True)
    approvals = ApprovalService(
        sessions,
        clock=clock,
        actions=default_actions.copy(),
        executors=executors,
        confirmations=default_confirmations.copy(),
    )
    hierarchy = Hierarchy(
        sessions, clock=clock, adapters=ADAPTERS, approvals=approvals, settings=settings
    )
    return World(hierarchy, approvals, sessions, clock, settings, executors, "site")
