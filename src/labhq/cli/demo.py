"""`labhq demo`: one project, one manager, one worker and one task, end to end (plan §10).

The demo migrates the database, registers a project (by default a fresh repository with a
local bare remote under the data directory), adds a manager and a worker that reports to
it, assigns the worker a task and runs one scheduler pass. It prints what Phase 1 promises:
the task branch with its commit, the `cost_events` row and the pending push approval.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer
from sqlalchemy import select

from labhq.cli.context import CliError, Context, execute, fail, load_settings
from labhq.cli.engine import Engine, PassReport, cli_adapters
from labhq.cli.render import approval_line, cost_line, run_line
from labhq.cli.work import create_agent, create_project, create_task, migrate, parse_budget
from labhq.db.enums import AgentStatus
from labhq.db.models import CostEvent
from labhq.worktrees import GitError
from labhq.worktrees.git import run_git

IDENTITY = ("-c", "user.name=labhq demo", "-c", "user.email=demo@labhq.invalid")
TASK_TITLE = "Add a HELLO file"
TASK_DESCRIPTION = (
    "Create HELLO.md with one sentence that greets the reader, then commit it with "
    "`git add HELLO.md && git commit -m 'docs: add HELLO.md'`. Do not push; the engine "
    "publishes after a human approves."
)
# Bounds a real run; the fake ignores it.
WORKER_CONFIG = {"output_recipient": "agent", "max_turns": 10}
MANAGER_CONFIG = {"output_recipient": "user"}


def bootstrap_repository(root: Path) -> Path:
    """A repository with one commit on `main`, published to a bare remote beside it."""
    project, remote = root / "project", root / "remote.git"
    if project.exists() or remote.exists():
        raise CliError(f"{root} already holds a demo; pass another --name")
    root.mkdir(parents=True)
    run_git("init", "--quiet", "--bare", "--initial-branch=main", str(remote), cwd=root)
    run_git("init", "--quiet", "--initial-branch=main", str(project), cwd=root)
    (project / "README.md").write_text("# labhq demo project\n", encoding="utf-8")
    run_git("add", "README.md", cwd=project)
    run_git(*IDENTITY, "commit", "--quiet", "-m", "chore: start the demo project", cwd=project)
    run_git("remote", "add", "origin", str(remote), cwd=project)
    run_git("push", "--quiet", "origin", "main", cwd=project)
    return project


@dataclass
class DemoResult:
    report: PassReport
    costs: list[CostEvent]


async def run_demo(
    context: Context, name: str, repo: Path, adapter: str, budget: str
) -> DemoResult:
    project = await create_project(context, name, repo, None)
    manager = await create_agent(
        context,
        project=project.name,
        role="manager",
        title="Project manager",
        adapter=adapter,
        config=MANAGER_CONFIG,
        # Running the demo is the operator's approval of its two agents.
        status=AgentStatus.ACTIVE,
    )
    worker = await create_agent(
        context,
        project=project.name,
        role="worker",
        title="Worker",
        adapter=adapter,
        reports_to=manager.id,
        config=WORKER_CONFIG,
        budget=parse_budget(budget),
        status=AgentStatus.ACTIVE,
    )
    typer.echo(f"project {project.id} {project.name}: {project.repo_path}")
    typer.echo(f"manager: agent {manager.id}; worker: agent {worker.id} reports to {manager.id}")
    task = await create_task(
        context,
        project=project.name,
        title=TASK_TITLE,
        description=TASK_DESCRIPTION,
        assignee=worker.id,
    )
    typer.echo(f"task {task.id} {task.title}, assigned to agent {worker.id}")
    report = await Engine(context).run_pass()
    async with context.sessions() as db:
        run_ids = [run.id for run in report.runs]
        costs = list(await db.scalars(select(CostEvent).where(CostEvent.run_id.in_(run_ids))))
    return DemoResult(report, costs)


def demo(
    adapter: Annotated[
        str, typer.Option(help="fake (default, no model) or claude (your real Claude login).")
    ] = "fake",
    name: Annotated[
        str, typer.Option(help="Project name; also names the demo directory.")
    ] = "demo",
    repo: Annotated[
        Path | None,
        typer.Option(
            help="Use this repository (it needs an `origin` remote) instead of a fresh one."
        ),
    ] = None,
    worker_budget_usd: Annotated[
        str, typer.Option(help="The worker's monthly budget in USD.")
    ] = "1",
) -> None:
    """Run the Phase 1 demo: task -> worktree branch with a commit -> cost -> pending push."""
    if adapter not in cli_adapters().adapter_keys():
        fail(f"no adapter registered as {adapter!r}; try fake or claude")
    settings = load_settings()
    try:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        migrate(settings.resolved_database_url)
        project_repo = (
            repo.expanduser().resolve()
            if repo
            else bootstrap_repository(settings.data_dir / "demo" / name)
        )
    except (CliError, GitError, OSError) as error:
        fail(str(error))

    result = execute(
        lambda context: run_demo(context, name, project_repo, adapter, budget=worker_budget_usd)
    )
    for run in result.report.runs:
        typer.echo(run_line(run))
    for cost in result.costs:
        typer.echo(cost_line(cost))
    for approval in result.report.approvals:
        typer.echo(f"branch: {approval.payload['branch']}")
        typer.echo(f"commit: {approval.payload['commit']}")
        typer.echo(approval_line(approval))
        typer.echo(f"approve with: labhq approvals approve {approval.id}")
    if result.report.failed or not result.costs or not result.report.approvals:
        fail("the demo did not produce a succeeded run, a cost row and a pending push")
