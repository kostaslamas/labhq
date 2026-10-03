from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path

import pytest
from claude_agent_sdk import HookMatcher
from sqlalchemy import select

from labhq.adapters import FakeScript, default_registry
from labhq.cli import workspace
from labhq.cli.context import Context
from labhq.cli.engine import Engine
from labhq.cli.fake_worker import WORK_FILE, CommittingFakeAdapter
from labhq.cli.work import assignment, create_agent, create_project, create_task
from labhq.cli.workspace import PRE_TOOL_USE, WARNING_EVENT, run_hooks
from labhq.clock import FakeClock
from labhq.db import create_engine, session_factory
from labhq.db.enums import AgentStatus
from labhq.db.models import RunEvent, Task
from labhq.economy import RtkHook, rtk_hook
from labhq.economy.rtk import RTK_MISSING
from labhq.guards import deny_publishing
from labhq.scheduler import enqueue
from labhq.settings import Settings
from labhq.worktrees import PUSH_DISABLED_URL
from labhq.worktrees.git import run_git


@pytest.fixture
async def context(database_url: str, data_dir: Path, clock: FakeClock) -> AsyncIterator[Context]:
    engine = create_engine(database_url)
    try:
        yield Context(
            Settings(data_dir=data_dir, database_url=database_url), session_factory(engine), clock
        )
    finally:
        await engine.dispose()


async def assigned_task(context: Context, repo: Path) -> int:
    await create_project(context, "wired", repo, None)
    worker = await create_agent(
        context,
        project="wired",
        role="worker",
        title="Worker",
        adapter="fake",
        status=AgentStatus.ACTIVE,
    )
    task = await create_task(context, project="wired", title="Wire it", assignee=worker.id)
    return task.id


async def test_a_scheduled_run_works_in_its_task_worktree_with_the_guard(
    context: Context, repo: Path, data_dir: Path
) -> None:
    script = FakeScript()
    registry = default_registry.copy()
    registry.register("fake", lambda: CommittingFakeAdapter(script), replace=True)
    task_id = await assigned_task(context, repo)

    report = await Engine(context, registry).run_pass()

    [request] = script.requests
    assert request.cwd is not None
    assert request.cwd.is_relative_to(data_dir / "worktrees")
    branch = run_git("branch", "--show-current", cwd=request.cwd).strip()
    assert branch.startswith(f"labhq/task-{task_id}-")
    assert run_git("config", "--get", "remote.origin.pushurl", cwd=request.cwd).strip() == (
        PUSH_DISABLED_URL
    )
    assert request.hooks is not None
    guard = request.hooks[PRE_TOOL_USE][0]
    assert guard.matcher == "Bash"
    assert guard.hooks == [deny_publishing]
    assert (request.cwd / WORK_FILE).is_file()
    assert [run.status for run in report.runs] == ["succeeded"]
    assert len(report.approvals) == 1


async def test_a_second_run_on_the_task_reuses_its_worktree(context: Context, repo: Path) -> None:
    script = FakeScript()
    registry = default_registry.copy()
    registry.register("fake", lambda: CommittingFakeAdapter(script), replace=True)
    task_id = await assigned_task(context, repo)
    engine = Engine(context, registry)
    await engine.run_pass()
    async with context.sessions() as db:
        task = await db.get_one(Task, task_id)
        assert task.assignee_id is not None
        again = replace(assignment(task, task.assignee_id), idempotency_key="assignment:again")
        await enqueue(db, again, context.clock)
        await db.commit()

    report = await engine.run_pass()

    first, second = script.requests
    assert first.cwd == second.cwd
    # A new commit on the same branch is a new push to approve; the old one stays pending.
    assert len(report.approvals) == 1


@pytest.mark.parametrize(
    "rtk_present",
    [
        False,
        pytest.param(True, marks=pytest.mark.posix_only("the rtk stub is a POSIX shell script")),
    ],
)
async def test_a_run_without_rtk_records_the_warning_in_its_events(
    context: Context, repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rtk_present: bool
) -> None:
    search = tmp_path / "rtk-bin"
    search.mkdir()
    if rtk_present:
        (search / "rtk").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        (search / "rtk").chmod(0o755)
    monkeypatch.setattr(workspace, "rtk_hook", lambda: rtk_hook(search_path=str(search)))
    registry = default_registry.copy()
    registry.register("fake", lambda: CommittingFakeAdapter(FakeScript()), replace=True)
    await assigned_task(context, repo)

    [run] = (await Engine(context, registry).run_pass()).runs

    async with context.sessions() as db:
        events = list(await db.scalars(select(RunEvent).where(RunEvent.run_id == run.id)))
    warnings = [event.payload["code"] for event in events if event.kind == WARNING_EVENT]
    assert warnings == ([] if rtk_present else [RTK_MISSING])


def test_the_push_guard_runs_before_the_rtk_rewrite() -> None:
    async def rewrite(*_: object) -> dict[str, object]:
        return {}

    rtk = RtkHook(
        binary=Path("/usr/bin/rtk"), matchers=[HookMatcher(matcher="Bash", hooks=[rewrite])]
    )

    [guard, rewriter] = run_hooks(rtk)[PRE_TOOL_USE]

    assert guard.hooks == [deny_publishing]
    assert rewriter.hooks == [rewrite]


def test_without_rtk_only_the_push_guard_is_registered() -> None:
    [guard] = run_hooks(RtkHook(binary=None))[PRE_TOOL_USE]
    assert guard.hooks == [deny_publishing]
