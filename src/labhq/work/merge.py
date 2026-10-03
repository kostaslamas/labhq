"""Ask the owner to merge a task's branch: one pending heavy approval, nothing merged yet.

The approval service commits in its own session, so the request is recorded (with its
notification) whatever the caller's transaction does afterwards.
"""

import asyncio
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.approvals import MERGE_ACTION, ApprovalService, MergeError, merge_payload
from labhq.approvals.merge import DEFAULT_TARGET
from labhq.clock import Clock
from labhq.db.enums import ApprovalStatus
from labhq.db.models import Approval, Project, Task
from labhq.work.service import WorkError
from labhq.worktrees import GitError
from labhq.worktrees.git import run_git
from labhq.worktrees.manager import BRANCH_PREFIX, branch_name


def task_branch(repo: Path, task: Task) -> str:
    """The task's branch in the project repository, whatever slug its title had then."""
    expected = branch_name(task.id, task.title)
    prefix = f"{BRANCH_PREFIX}{task.id}"
    listing = run_git("for-each-ref", "--format=%(refname:short)", "refs/heads/labhq/", cwd=repo)
    branches = [b for b in listing.split() if b == prefix or b.startswith(f"{prefix}-")]
    if expected in branches:
        return expected
    if len(branches) != 1:
        raise WorkError(f"task {task.id} has no single branch to merge")
    return branches[0]


async def _pending_duplicate(
    db: AsyncSession, task_id: int, payload: dict[str, object]
) -> Approval | None:
    pending = await db.scalars(
        select(Approval).where(
            Approval.type == MERGE_ACTION,
            Approval.task_id == task_id,
            Approval.status == ApprovalStatus.PENDING,
        )
    )
    return next((approval for approval in pending if approval.payload == payload), None)


def _pin(repo: Path, task: Task, target: str, remote: str) -> dict[str, object]:
    # Messages stay one short line: a voice caller hears them. The cause keeps git's detail.
    try:
        return merge_payload(repo, task_branch(repo, task), target, remote)
    except MergeError as error:
        raise WorkError(str(error)) from error
    except ValidationError as error:
        raise WorkError(f"task {task.id} cannot be merged into {target}") from error
    except (GitError, OSError) as error:
        raise WorkError(f"git could not resolve task {task.id} and {target}") from error


async def request_merge(
    db: AsyncSession,
    clock: Clock,
    task_id: int,
    *,
    target: str = DEFAULT_TARGET,
    remote: str = "origin",
) -> Approval:
    """Request the heavy `merge` approval for a task's branch into `target`.

    The same request while one is still pending returns it, so a retried voice order or a
    repeated command never asks twice.
    """
    task = await db.get(Task, task_id)
    if task is None:
        raise WorkError(f"no task {task_id}")
    project = await db.get_one(Project, task.project_id)
    payload = await asyncio.to_thread(_pin, Path(project.repo_path), task, target, remote)
    existing = await _pending_duplicate(db, task.id, payload)
    if existing is not None:
        return existing
    if db.bind is None:
        raise RuntimeError("request_merge needs a session bound to an engine")
    service = ApprovalService(async_sessionmaker(db.bind, expire_on_commit=False), clock=clock)
    return await service.request(MERGE_ACTION, payload, task_id=task.id)
