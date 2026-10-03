"""After a task run ends, read the status file its agent keeps in the task worktree."""

import asyncio
import logging
from collections.abc import Iterable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.callcenter.status import IngestResult, ingest_status
from labhq.cli.workspace import project_worktrees
from labhq.clock import Clock
from labhq.db.models import Project, Run, Task
from labhq.settings import Settings
from labhq.worktrees import GitError

log = logging.getLogger(__name__)


async def ingest_statuses(
    sessions: async_sessionmaker[AsyncSession],
    clock: Clock,
    settings: Settings,
    run_ids: Iterable[int],
) -> list[IngestResult]:
    """Ingest the status of each finished task run's worktree; report only what changed."""
    changed: list[IngestResult] = []
    for run_id in sorted(set(run_ids)):
        async with sessions() as db:
            run = await db.get_one(Run, run_id)
            if run.task_id is None:
                continue
            task = await db.get_one(Task, run.task_id)
            project = await db.get_one(Project, task.project_id)
            try:
                worktree = await asyncio.to_thread(
                    project_worktrees(settings, project).find, task.id
                )
            except (GitError, OSError):
                # A run that failed because its repository vanished must still report that.
                log.warning("cannot read the worktree of task %s; no status ingested", task.id)
                continue
            if worktree is None:
                continue
            result = await ingest_status(
                db, clock, agent_id=run.agent_id, task_id=task.id, worktree=worktree.path
            )
            await db.commit()
            if result.changed:
                changed.append(result)
    return changed
