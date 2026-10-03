"""`labhq demo`: one project, one manager, one worker and one task, end to end (plan §10).

With `--adapter fake` (the default) no model runs: a scripted worker writes a file in its
worktree and commits it, so the rest of the engine (checkout, cost, push approval) runs
for real. With `--adapter claude` the worker is Claude Code on the user's own login.
"""

import asyncio
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Annotated

import typer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.adapters import AdapterError, FakeAdapter, RunRequest
from labhq.adapters import default_registry as builtin_adapters
from labhq.approvals import PUSH_ACTION
from labhq.cli.run import build_engine
from labhq.cli.runtime import CliError, migrate, reported, run_with_database, settings
from labhq.cli.work import AgentSpec, TaskSpec, add_agent, add_project, add_task
from labhq.clock import Clock, SystemClock
from labhq.db.enums import ApprovalStatus
from labhq.db.models import Approval, CostEvent, Project, Run
from labhq.money import format_micros
from labhq.settings import Settings
from labhq.worktrees import worker_environment
from labhq.worktrees.git import run_git

DEMO_FILE = "HELLO.md"
DEMO_TASK = TaskSpec(
    title="Add a hello file",
    description=(
        f"Create {DEMO_FILE} at the repository root with one line that greets the reader, "
        f"then commit it with git (`git add {DEMO_FILE}` and `git commit`). Do not push."
    ),
)
# Commits made by labhq itself, never by the user: a fixed identity, so no git config is
# needed on a fresh machine.
ENGINE_IDENTITY = ("-c", "user.name=labhq", "-c", "user.email=labhq@localhost")


class CommittingFakeAdapter(FakeAdapter):
    """The fake adapter plus the one thing the demo needs from a worker: a commit."""

    async def start(self, request: RunRequest) -> None:
        await super().start(request)
        if request.cwd is None:
            raise AdapterError("the demo worker needs a worktree")
        await asyncio.to_thread(commit_demo_file, request.cwd)


def commit_demo_file(worktree: Path) -> None:
    (worktree / DEMO_FILE).write_text("Hello from the labhq demo worker.\n", encoding="utf-8")
    # The worker's environment: whatever it commits, it holds no way to push.
    env = worker_environment()
    run_git("add", DEMO_FILE, cwd=worktree, env=env)
    run_git(*ENGINE_IDENTITY, "commit", "--quiet", "-m", "Add a hello file", cwd=worktree, env=env)


def sandbox_repository(root: Path) -> Path:
    """A fresh repository with one commit and a local bare `origin` to push to."""
    remote = root / "origin.git"
    repo = root / "project"
    root.mkdir(parents=True, exist_ok=False)
    run_git("init", "--quiet", "--bare", "--initial-branch=main", str(remote), cwd=root)
    run_git("init", "--quiet", "--initial-branch=main", str(repo), cwd=root)
    (repo / "README.md").write_text("A labhq demo project.\n", encoding="utf-8")
    run_git("add", "README.md", cwd=repo)
    run_git(*ENGINE_IDENTITY, "commit", "--quiet", "-m", "Start the demo project", cwd=repo)
    run_git("remote", "add", "origin", str(remote), cwd=repo)
    run_git("push", "--quiet", "origin", "main", cwd=repo)
    return repo


async def free_project_name(db: AsyncSession, base: str) -> str:
    taken = set(await db.scalars(select(Project.name).where(Project.name.startswith(base))))
    if base not in taken:
        return base
    suffix = 2
    while f"{base}-{suffix}" in taken:
        suffix += 1
    return f"{base}-{suffix}"


@dataclass(frozen=True)
class DemoResult:
    run: Run
    cost: CostEvent
    approval: Approval


class OnePass:
    """One scheduler pass with the demo's adapters: the committing fake replaces `fake`."""

    def __init__(self, config: Settings, adapter: str, clock: Clock) -> None:
        self._config = config
        self._clock = clock
        self._registry = builtin_adapters.copy()
        if adapter == "fake":
            self._registry.register("fake", CommittingFakeAdapter, replace=True)

    async def __call__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        await build_engine(sessions, self._config, self._clock, self._registry).one_pass()


async def run_demo(
    sessions: async_sessionmaker[AsyncSession],
    clock: Clock,
    repo: Path,
    adapter: str,
    one_pass: OnePass,
) -> DemoResult:
    async with sessions() as db:
        project = await add_project(db, clock, await free_project_name(db, "demo"), repo, None)
        manager = await add_agent(db, clock, project, AgentSpec("manager", "Manager", adapter))
        worker = await add_agent(
            db, clock, project, AgentSpec("worker", "Worker", adapter, reports_to=manager.id)
        )
        task, _ = await add_task(db, clock, project, replace(DEMO_TASK, assignee_id=worker.id))
        await db.commit()
    typer.echo(f"project {project.id} {project.name} at {project.repo_path}")
    typer.echo(f"manager {manager.id}, worker {worker.id} reporting to it ({adapter})")
    typer.echo(f"task {task.id} {task.title!r}, assigned to worker {worker.id}")

    await one_pass(sessions)
    async with sessions() as db:
        run = await db.scalar(select(Run).where(Run.task_id == task.id).order_by(Run.id.desc()))
        if run is None:
            raise CliError(f"the scheduler started no run for task {task.id}")
        cost = await db.scalar(select(CostEvent).where(CostEvent.run_id == run.id))
        approval = await db.scalar(
            select(Approval).where(
                Approval.task_id == task.id,
                Approval.type == PUSH_ACTION,
                Approval.status == ApprovalStatus.PENDING,
            )
        )
    if cost is None or approval is None:
        missing = "a cost_events row" if cost is None else "a commit to push"
        raise CliError(f"run {run.id} ended {run.status} without {missing}: {run.exit}")
    return DemoResult(run, cost, approval)


def print_result(result: DemoResult) -> None:
    run, cost, approval = result.run, result.cost, result.approval
    payload = approval.payload
    typer.echo(f"run {run.id} {run.status}")
    typer.echo(f"branch {payload['branch']}")
    typer.echo(f"commit {payload['commit']}")
    typer.echo(
        f"cost_events {cost.id}: run {cost.run_id}, {format_micros(cost.cost_micros)} "
        f"({cost.cost_micros} micros), {cost.input_tokens} tokens in, "
        f"{cost.output_tokens} out, model {cost.model}"
    )
    typer.echo(f"approval {approval.id} {approval.status}: {approval.type} to {payload['url']}")
    typer.echo(f"next: labhq approvals approve {approval.id}")


def demo(
    adapter: Annotated[
        str, typer.Option(help="fake (no model, the default) or claude (your own login).")
    ] = "fake",
    repo: Annotated[
        Path | None,
        typer.Option(help="A git repository with an origin remote; default: a fresh sandbox."),
    ] = None,
) -> None:
    """Run the Phase 1 demo: a task becomes a commit, a cost row and a pending push."""
    config = settings()
    clock = SystemClock()
    with reported():
        if adapter not in builtin_adapters.adapter_keys():
            known = ", ".join(builtin_adapters.adapter_keys())
            raise CliError(f"no adapter {adapter!r}; known adapters: {known}")
        migrate(config)
        if repo is None:
            stamp = clock.now().strftime("%Y%m%dT%H%M%S%fZ")
            repo = sandbox_repository(config.data_dir / "demo" / stamp)
    target = repo

    async def job(sessions: async_sessionmaker[AsyncSession]) -> None:
        print_result(
            await run_demo(sessions, clock, target, adapter, OnePass(config, adapter, clock))
        )

    run_with_database(job, config)
