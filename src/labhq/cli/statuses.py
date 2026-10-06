"""After a task run ends, read the status file its agent keeps in the task worktree."""

import asyncio
import logging
from collections.abc import Iterable
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.callcenter.status import IngestResult, ingest_status
from labhq.cli.workspace import plain_status_path, project_worktrees
from labhq.clock import Clock
from labhq.db.models import Department, Project, Run, Task
from labhq.settings import Settings
from labhq.work import has_git_commit
from labhq.worktrees import GitError

log = logging.getLogger(__name__)


async def _owner(db: AsyncSession, task: Task) -> Project | Department:
    if task.department_id is not None:
        return await db.get_one(Department, task.department_id)
    assert task.project_id is not None
    return await db.get_one(Project, task.project_id)


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
            owner = await _owner(db, task)
            # A department's folder is plain: there is no worktree to look for.
            folder = Path(owner.folder if isinstance(owner, Department) else owner.repo_path)
            if folder.is_dir() and (
                isinstance(owner, Department) or not await asyncio.to_thread(has_git_commit, folder)
            ):
                result = await ingest_status(
                    db,
                    clock,
                    agent_id=run.agent_id,
                    task_id=task.id,
                    worktree=folder,
                    relative_path=plain_status_path(task.id),
                )
                await db.commit()
                if result.changed:
                    changed.append(result)
                continue
            if isinstance(owner, Department):
                # Its folder is missing: there is nothing to ingest.
                continue
            try:
                worktree = await asyncio.to_thread(project_worktrees(settings, owner).find, task.id)
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
