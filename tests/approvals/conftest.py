from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.approvals import (
    ActionType,
    ApprovalService,
    ConfirmationKind,
    Executor,
    Registry,
    default_actions,
    default_confirmations,
    default_executors,
)
from labhq.clock import FakeClock
from labhq.db import create_engine, session_factory
from labhq.worktrees import Worktree, Worktrees
from tests.db.factories import project_agent_task
from tests.worktrees.conftest import isolated_git, remote, repo
from tests.worktrees.gitrepo import commit_file

# Approved pushes run real git against a local bare remote, under the same isolation.
__all__ = ["isolated_git", "remote", "repo"]


@dataclass
class World:
    service: ApprovalService
    sessions: async_sessionmaker[AsyncSession]
    clock: FakeClock
    actions: Registry[ActionType]
    executors: Registry[Executor]
    confirmations: Registry[ConfirmationKind]
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
    async with sessions() as db:
        _, agent, task = await project_agent_task(db, clock)
        await db.commit()
    # Copies, so a test that registers a new variant never leaks it into another test.
    actions = default_actions.copy()
    executors = default_executors.copy()
    confirmations = default_confirmations.copy()
    service = ApprovalService(
        sessions,
        clock=clock,
        actions=actions,
        executors=executors,
        confirmations=confirmations,
    )
    return World(service, sessions, clock, actions, executors, confirmations, agent.id, task.id)


@pytest.fixture
def worktree(repo: Path, tmp_path: Path) -> Worktree:
    """A task worktree with one commit the remote has not seen."""
    worktree = Worktrees(repo, tmp_path / "worktrees").create(7, "publish me")
    commit_file(worktree.path, "work.txt")
    return worktree
