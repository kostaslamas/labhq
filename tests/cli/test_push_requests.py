"""The engine asks to push a task branch once per commit, never twice."""

import asyncio
import sqlite3
from contextlib import closing
from pathlib import Path

from labhq.approvals import ApprovalService
from labhq.cli.engine import request_pushes
from labhq.clock import SystemClock
from labhq.db import create_engine, session_factory
from labhq.settings import DATABASE_FILENAME, Settings
from labhq.worktrees import default_root
from tests.cli.conftest import Cli


async def request_again(run_id: int) -> tuple[int, dict[int, str]]:
    config = Settings()
    engine = create_engine(config.resolved_database_url)
    try:
        sessions = session_factory(engine)
        approvals = ApprovalService(sessions, clock=SystemClock())
        outcome = await request_pushes(sessions, approvals, [run_id], default_root(config))
        return len(outcome.requested), outcome.skipped
    finally:
        await engine.dispose()


def test_a_pending_push_of_the_same_commit_is_not_requested_again(cli: Cli, repo: Path) -> None:
    cli.ok("demo", "--repo", str(repo))

    requested, skipped = asyncio.run(request_again(1))

    assert requested == 0
    assert "already pending" in skipped[1]
    assert cli.rows("SELECT count(*) FROM approvals") == [(1,)]


def test_a_run_that_did_not_succeed_asks_for_nothing(cli: Cli, repo: Path) -> None:
    cli.ok("demo", "--repo", str(repo))
    with closing(sqlite3.connect(cli.data_dir / DATABASE_FILENAME)) as db:
        db.execute("UPDATE runs SET status = 'failed'")
        db.execute("UPDATE approvals SET status = 'rejected'")
        db.commit()

    assert asyncio.run(request_again(1)) == (0, {})
