"""Where a run works and which hooks guard it: the wiring the scheduler leaves to its caller.

The scheduler starts runs with an agent, a task and a prompt only. `WorkspaceRunService`
fills in the rest for every run it starts: a task run works in the task's own worktree
(created on first use, push disabled), and every run gets the push guard ahead of the
`rtk` rewrite hook, so a rewritten command can never slip past the guard's verdict.
"""

import asyncio
import logging
from pathlib import Path
from typing import Any

from claude_agent_sdk import HookMatcher
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.adapters import AdapterRegistry
from labhq.clock import Clock
from labhq.db.models import Project, Task
from labhq.economy import RtkHook, rtk_hook
from labhq.guards import push_guard_matcher
from labhq.runs import ActiveRun, RunService
from labhq.settings import Settings
from labhq.worktrees import Worktree, Worktrees, default_root

log = logging.getLogger(__name__)

PRE_TOOL_USE = "PreToolUse"
WARNING_EVENT = "warning"


def project_worktrees(settings: Settings, project: Project) -> Worktrees:
    # One root per project: task ids are global, but `find` only sees one repository.
    return Worktrees(Path(project.repo_path), default_root(settings) / f"project-{project.id}")


def ensure_worktree(worktrees: Worktrees, task: Task) -> Worktree:
    return worktrees.find(task.id) or worktrees.create(task.id, task.title)


def run_hooks(rtk: RtkHook) -> dict[str, list[HookMatcher]]:
    """The guard first: hooks run in order, and only the guard decides; rtk only rewrites."""
    return {PRE_TOOL_USE: [push_guard_matcher(), *rtk.matchers]}


class WorkspaceRunService(RunService):
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        clock: Clock,
        registry: AdapterRegistry,
        settings: Settings,
        rtk: RtkHook | None = None,
    ) -> None:
        super().__init__(sessions, clock=clock, registry=registry)
        self._workspace_sessions = sessions
        self._settings = settings
        self._rtk = rtk if rtk is not None else rtk_hook()

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
        if cwd is None and task_id is not None:
            cwd = await self._task_worktree(task_id)
        active = await super().start(
            agent_id=agent_id,
            task_id=task_id,
            prompt=prompt,
            cwd=cwd,
            hooks=hooks if hooks is not None else run_hooks(self._rtk),
            run_id=run_id,
        )
        # A log line scrolls away; the run's own events are where a lost saving stays visible.
        for warning in self._rtk.warnings:
            await active.note(WARNING_EVENT, warning.as_event_payload())
        return active

    async def _task_worktree(self, task_id: int) -> Path:
        async with self._workspace_sessions() as db:
            task = await db.get_one(Task, task_id)
            project = await db.get_one(Project, task.project_id)
        worktrees = project_worktrees(self._settings, project)
        # git runs as a child process; keep the event loop free for live runs meanwhile.
        worktree = await asyncio.to_thread(ensure_worktree, worktrees, task)
        log.info("task %s works in %s on %s", task_id, worktree.path, worktree.branch)
        return worktree.path
