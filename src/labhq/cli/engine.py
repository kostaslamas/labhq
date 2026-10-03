"""The engine as the CLI assembles it: scheduler, worktrees, worker hooks and push requests.

The scheduler starts runs without a working directory. `TaskRunService` gives every task
run its worktree, the push guard and the `rtk` hook. After a run succeeds, the engine,
never the agent, asks for approval to push the task branch when it carries new commits
(plan §5).
"""

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.adapters import AdapterRegistry
from labhq.adapters import default_registry as builtin_adapters
from labhq.approvals import PUSH_ACTION, ApprovalService, push_payload
from labhq.clock import Clock
from labhq.db.enums import ApprovalStatus, RunStatus
from labhq.db.models import Approval, Project, Run, RunEvent, Task
from labhq.economy import RtkHook, rtk_hook
from labhq.guards import push_guard_matcher
from labhq.runs import ActiveRun, RunService
from labhq.scheduler import Scheduler, TickReport
from labhq.worktrees import Worktree, Worktrees
from labhq.worktrees.git import run_git

PUSH_REMOTE = "origin"
# `ActiveRun` numbers stream events from 1; seq 0 is the engine's note before the stream.
PREAMBLE_SEQ = 0


def worktrees_for(project: Project, root: Path) -> Worktrees:
    return Worktrees(Path(project.repo_path), root)


async def task_worktree(task: Task, project: Project, root: Path) -> Worktree:
    """The task's worktree, created on its first run."""
    worktrees = worktrees_for(project, root)
    existing = await asyncio.to_thread(worktrees.find, task.id)
    if existing is not None:
        return existing
    return await asyncio.to_thread(worktrees.create, task.id, task.title)


class TaskRunService(RunService):
    """Runs every task in its worktree, with the push guard and the `rtk` hook."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        clock: Clock,
        worktree_root: Path,
        registry: AdapterRegistry = builtin_adapters,
        rtk: RtkHook | None = None,
    ) -> None:
        super().__init__(sessions, clock=clock, registry=registry)
        self._root = worktree_root
        self._rtk = rtk if rtk is not None else rtk_hook()

    def worker_hooks(self) -> dict[str, Any]:
        return {"PreToolUse": [push_guard_matcher(), *self._rtk.matchers]}

    async def start(
        self,
        *,
        agent_id: int,
        task_id: int | None,
        prompt: str,
        cwd: Path | None = None,
        hooks: dict[str, Any] | None = None,
        run_id: int | None = None,
    ) -> ActiveRun:
        if task_id is not None and cwd is None:
            async with self._sessions() as db:
                task = await db.get_one(Task, task_id)
                project = await db.get_one(Project, task.project_id)
            cwd = (await task_worktree(task, project, self._root)).path
        if run_id is not None:
            await self._note_warnings(run_id)
        return await super().start(
            agent_id=agent_id,
            task_id=task_id,
            prompt=prompt,
            cwd=cwd,
            hooks=hooks if hooks is not None else self.worker_hooks(),
            run_id=run_id,
        )

    async def _note_warnings(self, run_id: int) -> None:
        # docs/checks/rtk-ab.md looks for this event to tell run A from run B.
        # The rtk hook reports at most one warning, its absence, so one preamble slot fits.
        if not self._rtk.warnings:
            return
        async with self._sessions() as db:
            db.add(
                RunEvent(
                    run_id=run_id,
                    seq=PREAMBLE_SEQ,
                    kind="warning",
                    payload=self._rtk.warnings[0].as_event_payload(),
                    created_at=self._clock.now(),
                )
            )
            await db.commit()


def commits_ahead(repo: Path, branch: str) -> int:
    """Commits on `branch` that the repository's checked-out HEAD does not have."""
    return int(run_git("rev-list", "--count", f"HEAD..refs/heads/{branch}", cwd=repo).strip())


@dataclass
class PushRequests:
    requested: list[Approval] = field(default_factory=list)
    # Run id to why no push was requested for it, when the reason is worth reporting.
    skipped: dict[int, str] = field(default_factory=dict)


async def request_pushes(
    sessions: async_sessionmaker[AsyncSession],
    approvals: ApprovalService,
    run_ids: Iterable[int],
    worktree_root: Path,
) -> PushRequests:
    """Ask to push the branch of every succeeded task run that left new commits."""
    outcome = PushRequests()
    for run_id in run_ids:
        async with sessions() as db:
            run = await db.get_one(Run, run_id)
            if run.status is not RunStatus.SUCCEEDED or run.task_id is None:
                continue
            task = await db.get_one(Task, run.task_id)
            project = await db.get_one(Project, task.project_id)
        repo = Path(project.repo_path)
        worktree = await asyncio.to_thread(worktrees_for(project, worktree_root).find, task.id)
        if worktree is None or not await asyncio.to_thread(commits_ahead, repo, worktree.branch):
            continue
        payload = await asyncio.to_thread(push_payload, repo, worktree.branch, PUSH_REMOTE)
        if await _already_pending(sessions, task.id, payload["commit"]):
            outcome.skipped[run_id] = f"a push of {payload['commit'][:12]} is already pending"
            continue
        approval = await approvals.request(
            PUSH_ACTION, payload, task_id=task.id, agent_id=run.agent_id
        )
        outcome.requested.append(approval)
    return outcome


async def _already_pending(
    sessions: async_sessionmaker[AsyncSession], task_id: int, commit: str
) -> bool:
    async with sessions() as db:
        pending = await db.scalars(
            select(Approval).where(
                Approval.type == PUSH_ACTION,
                Approval.task_id == task_id,
                Approval.status == ApprovalStatus.PENDING,
            )
        )
        return any(approval.payload.get("commit") == commit for approval in pending)


@dataclass
class Pass:
    """What one pass did: the scheduler's reports and the pushes it asked for."""

    reports: list[TickReport]
    pushes: PushRequests

    @property
    def started(self) -> list[int]:
        return [run_id for report in self.reports for run_id in report.started]

    @property
    def finished(self) -> list[int]:
        return [run_id for report in self.reports for run_id in report.finished]


@dataclass
class Engine:
    sessions: async_sessionmaker[AsyncSession]
    scheduler: Scheduler
    approvals: ApprovalService
    worktree_root: Path

    async def one_pass(self) -> Pass:
        """Start what may start, wait for those runs to end, then request their pushes."""
        try:
            reports = [await self.scheduler.tick(), await self.scheduler.settle()]
        finally:
            await self.scheduler.shutdown()
        return await self._after(reports)

    async def tick(self) -> Pass:
        """One scheduler tick of a loop: runs keep going across ticks."""
        return await self._after([await self.scheduler.tick()])

    async def _after(self, reports: list[TickReport]) -> Pass:
        finished = [run_id for report in reports for run_id in report.finished]
        pushes = await request_pushes(self.sessions, self.approvals, finished, self.worktree_root)
        return Pass(reports, pushes)
