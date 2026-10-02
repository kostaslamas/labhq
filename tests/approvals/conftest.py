from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.approvals import ApprovalService
from labhq.clock import FakeClock
from labhq.db import create_engine, session_factory
from labhq.worktrees import Worktree, Worktrees
from tests.worktrees.conftest import isolated_git, remote, repo
from tests.worktrees.gitrepo import commit_file

__all__ = ["isolated_git", "remote", "repo"]


@pytest.fixture
async def sessions(database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(database_url)
    try:
        yield session_factory(engine)
    finally:
        await engine.dispose()


@pytest.fixture
def service(sessions: async_sessionmaker[AsyncSession], clock: FakeClock) -> ApprovalService:
    return ApprovalService(sessions, clock=clock)


@pytest.fixture
def worktree(repo: Path, tmp_path: Path) -> Worktree:
    """A task worktree with one commit the worker made and cannot publish."""
    worktree = Worktrees(repo, tmp_path / "worktrees").create(7, "ship it")
    commit_file(worktree.path, "work.txt")
    return worktree
