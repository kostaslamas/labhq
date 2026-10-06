"""After a task run succeeds, ask the operator to approve publishing its branch.

Agents never push (plan §5, rule 5). Until agents can file requests themselves (the Call
Center tools, Phase 2), the engine files the push request on the worker's behalf once its
run succeeds with commits the project's checked-out branch does not have. The request pins
the commit and URL; nothing is published until a human approves it.
"""

import asyncio
from collections.abc import Iterable
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.approvals import PUSH_ACTION, ApprovalService, push_payload
from labhq.cli.workspace import project_worktrees
from labhq.db.enums import ApprovalStatus, RunStatus
from labhq.db.models import Approval, Project, Run, Task
from labhq.settings import Settings
from labhq.work import has_git_commit
from labhq.worktrees.git import run_git

PUSH_REMOTE = "origin"


def commits_ahead(repo: Path, branch: str) -> int:
    """Commits on `branch` that the repository's checked-out branch does not have."""
    return int(run_git("rev-list", "--count", f"HEAD..refs/heads/{branch}", cwd=repo).strip())


async def _push_target(db: AsyncSession, settings: Settings, run: Run) -> tuple[Path, str] | None:
    if run.status is not RunStatus.SUCCEEDED or run.task_id is None:
        return None
    task = await db.get_one(Task, run.task_id)
    if task.project_id is None:
        return None
    project = await db.get_one(Project, task.project_id)
    if not await asyncio.to_thread(has_git_commit, Path(project.repo_path)):
        return None
    worktrees = project_worktrees(settings, project)
    worktree = await asyncio.to_thread(worktrees.find, task.id)
    if worktree is None:
        return None
    if await asyncio.to_thread(commits_ahead, worktrees.repo, worktree.branch) == 0:
        return None
    return worktrees.repo, worktree.branch


async def _already_requested(db: AsyncSession, task_id: int, commit: str) -> bool:
    pending = await db.scalars(
        select(Approval).where(
            Approval.type == PUSH_ACTION,
            Approval.task_id == task_id,
            Approval.status == ApprovalStatus.PENDING,
        )
    )
    return any(approval.payload.get("commit") == commit for approval in pending)


async def request_pushes(
    sessions: async_sessionmaker[AsyncSession],
    approvals: ApprovalService,
    settings: Settings,
    run_ids: Iterable[int],
) -> list[Approval]:
    """File one pending push approval per succeeded task run with unpublished commits."""
    requested: list[Approval] = []
    for run_id in sorted(set(run_ids)):
        async with sessions() as db:
            run = await db.get_one(Run, run_id)
            target = await _push_target(db, settings, run)
            if target is None or run.task_id is None:
                continue
            repo, branch = target
            payload = await asyncio.to_thread(push_payload, repo, branch, PUSH_REMOTE)
            if await _already_requested(db, run.task_id, payload["commit"]):
                continue
        approval = await approvals.request(
            PUSH_ACTION, payload, task_id=run.task_id, agent_id=run.agent_id
        )
        requested.append(approval)
    return requested
