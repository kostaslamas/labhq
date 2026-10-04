"""`init`, `project add`, `agent add|approve` and `task add|merge`: who works on what."""

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated, Any

import typer
from alembic import command
from alembic.config import Config
from sqlalchemy import select

from labhq import work
from labhq.adapters.kinds import agent_choices
from labhq.cli.context import CliError, Context, execute, fail, load_settings
from labhq.cli.engine import cli_adapters
from labhq.db.enums import AgentStatus, TaskStatus
from labhq.db.models import Agent, Approval, Comment, Project, Task
from labhq.money import usd_to_micros

# Re-exported: callers and tests that build assignments through the CLI module keep working.
from labhq.work import assignment as assignment
from labhq.work.progress import owner_decide


def _migrations() -> Path:
    # A wheel carries them inside the package; a checkout keeps them next to `src/`.
    packaged = Path(__file__).resolve().parents[1] / "migrations"
    return packaged if packaged.is_dir() else Path(__file__).resolve().parents[3] / "migrations"


MIGRATIONS = _migrations()
DEFAULT_ADAPTER = "fake"
KIND_HELP = "The agent to run, one of: " + ", ".join(c.name for c in agent_choices()) + "."

project_app = typer.Typer(help="Register server directories as projects.", no_args_is_help=True)
agent_app = typer.Typer(help="Add agents and approve new ones.", no_args_is_help=True)
task_app = typer.Typer(
    help="Add tasks, assign them to agents and request their merge.", no_args_is_help=True
)


def migrate(url: str) -> None:
    if not (MIGRATIONS / "env.py").is_file():
        raise CliError(f"migrations not found at {MIGRATIONS}; run labhq from its checkout")
    # No ini file: the operator's logging setup stays as it is.
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")


def init() -> None:
    """Create the data directory and migrate the database to the latest schema."""
    settings = load_settings()
    try:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        migrate(settings.resolved_database_url)
    except (CliError, OSError) as error:
        fail(str(error))
    typer.echo(f"database ready: {settings.resolved_database_url}")


def parse_budget(value: str | None) -> int | None:
    """A USD amount typed by the operator, as integer micro-USD (ADR 0002)."""
    if value is None:
        return None
    try:
        return usd_to_micros(Decimal(value))
    except (InvalidOperation, ValueError) as error:
        raise CliError(f"budget must be a non-negative USD amount, got {value!r}") from error


def parse_config(value: str | None) -> dict[str, Any] | None:
    if value is None:
        return None
    try:
        parsed = json.loads(value)
    except ValueError as error:
        raise typer.BadParameter(f"--config is not JSON: {error}") from error
    if not isinstance(parsed, dict):
        raise typer.BadParameter("--config must be a JSON object")
    return parsed


async def create_project(context: Context, name: str, repo: Path, budget: int | None) -> Project:
    async with context.sessions() as db:
        project = await work.add_project(db, context.clock, name=name, repo=repo, budget=budget)
        await db.commit()
    return project


@project_app.command("add")
def project_add(
    name: Annotated[str, typer.Argument(help="A unique project name.")],
    repo: Annotated[Path, typer.Option(help="The project's directory on this machine.")],
    budget_usd: Annotated[
        str | None, typer.Option(help="Monthly budget in USD, for example 25 or 2.50.")
    ] = None,
) -> None:
    """Register an existing directory as a project."""

    async def body(context: Context) -> Project:
        return await create_project(
            context, name, work.check_project_directory(repo), parse_budget(budget_usd)
        )

    project = execute(body)
    typer.echo(f"project {project.id} {project.name}: {project.repo_path}")


async def create_agent(
    context: Context,
    *,
    project: str,
    role: str,
    title: str,
    adapter: str | None = None,
    kind: str | None = None,
    reports_to: int | None = None,
    config: dict[str, Any] | None = None,
    budget: int | None = None,
    status: AgentStatus = AgentStatus.PENDING_APPROVAL,
) -> Agent:
    async with context.sessions() as db:
        agent = await work.add_agent(
            db,
            context.clock,
            adapters=cli_adapters().adapter_keys(),
            project=project,
            role=role,
            title=title,
            adapter=adapter,
            kind=kind,
            reports_to=reports_to,
            config=config,
            budget=budget,
            status=status,
        )
        await db.commit()
    return agent


@agent_app.command("add")
def agent_add(
    project: Annotated[str, typer.Option(help="Project name or id.")],
    role: Annotated[str, typer.Option(help="The agent's role, for example manager or worker.")],
    title: Annotated[str, typer.Option(help="A human-readable title.")],
    kind: Annotated[str | None, typer.Option(help=KIND_HELP)] = None,
    adapter: Annotated[
        str | None,
        typer.Option(help="Adapter key (fake, claude, ollama, tmux); derived from --kind."),
    ] = None,
    config: Annotated[
        str | None, typer.Option(help="The rest of agents.config, as a JSON object.")
    ] = None,
    reports_to: Annotated[
        int | None, typer.Option(help="Id of the agent this one reports to.")
    ] = None,
    budget_usd: Annotated[str | None, typer.Option(help="Monthly budget in USD.")] = None,
) -> None:
    """Add an agent. New agents wait for `labhq agent approve` (plan §5, rule 4)."""

    async def body(context: Context) -> Agent:
        return await create_agent(
            context,
            project=project,
            role=role,
            title=title,
            adapter=adapter or (None if kind else DEFAULT_ADAPTER),
            kind=kind,
            reports_to=reports_to,
            config=parse_config(config),
            budget=parse_budget(budget_usd),
        )

    agent = execute(body)
    typer.echo(f"agent {agent.id} {agent.title} ({agent.role}, {agent.adapter}): {agent.status}")


@agent_app.command("approve")
def agent_approve(agent_id: Annotated[int, typer.Argument(help="The agent's id.")]) -> None:
    """Approve a new agent, so the scheduler may start its runs."""

    async def body(context: Context) -> Agent:
        async with context.sessions() as db:
            agent = await work.find_agent(db, agent_id)
            if agent.status is not AgentStatus.PENDING_APPROVAL:
                raise CliError(f"agent {agent_id} is {agent.status}, not pending approval")
            agent.status = AgentStatus.ACTIVE
            agent.updated_at = context.clock.now()
            await db.commit()
        return agent

    agent = execute(body)
    typer.echo(f"agent {agent.id} {agent.title}: {agent.status}")


async def create_task(
    context: Context,
    *,
    project: str,
    title: str,
    description: str = "",
    assignee: int | None = None,
    priority: int = 0,
) -> Task:
    async with context.sessions() as db:
        task = await work.add_task(
            db,
            context.clock,
            project=project,
            title=title,
            description=description,
            assignee=assignee,
            priority=priority,
        )
        await db.commit()
    return task


@task_app.command("add")
def task_add(
    project: Annotated[str, typer.Option(help="Project name or id.")],
    title: Annotated[str, typer.Option(help="What needs doing, in one line.")],
    description: Annotated[str, typer.Option(help="Details for the agent.")] = "",
    assignee: Annotated[
        int | None, typer.Option(help="Agent id; assigning wakes the agent on the next run.")
    ] = None,
    priority: Annotated[int, typer.Option(help="Higher runs first.")] = 0,
) -> None:
    """Add a task, optionally assigned to an agent."""

    async def body(context: Context) -> Task:
        return await create_task(
            context,
            project=project,
            title=title,
            description=description,
            assignee=assignee,
            priority=priority,
        )

    task = execute(body)
    assigned = f", assigned to agent {task.assignee_id}" if task.assignee_id else ""
    typer.echo(f"task {task.id} {task.title}{assigned}")


@task_app.command("accept")
def task_accept(
    task_id: Annotated[int, typer.Argument(help="Root objective to close.")],
    feedback: Annotated[str, typer.Option(help="Why the result meets the objective.")],
) -> None:
    """Accept a completed root objective as the owner."""

    async def body(context: Context) -> Task:
        async with context.sessions() as db:
            task = await db.get(Task, task_id)
            if task is None:
                raise work.WorkError(f"no task {task_id}")
            await owner_decide(db, context.clock, task, accept=True, feedback=feedback)
            await db.commit()
            return task

    task = execute(body)
    typer.echo(f"task {task.id}: {task.status}")


@task_app.command("pending")
def task_pending() -> None:
    """List root objectives waiting for the owner's decision."""

    async def body(context: Context) -> list[tuple[Task, Comment | None]]:
        async with context.sessions() as db:
            tasks = list(
                await db.scalars(
                    select(Task)
                    .where(
                        Task.parent_id.is_(None),
                        Task.status.in_({TaskStatus.IN_REVIEW, TaskStatus.BLOCKED}),
                    )
                    .order_by(Task.id)
                )
            )
            return [
                (
                    task,
                    await db.scalar(
                        select(Comment)
                        .where(Comment.task_id == task.id)
                        .order_by(Comment.id.desc())
                        .limit(1)
                    ),
                )
                for task in tasks
            ]

    for task, comment in execute(body):
        detail = f" — {comment.body}" if comment is not None else ""
        typer.echo(f"T{task.id} [{task.status}] {task.title}{detail}")


@task_app.command("return")
def task_return(
    task_id: Annotated[int, typer.Argument(help="Root objective to return.")],
    feedback: Annotated[str, typer.Option(help="What still needs work.")],
) -> None:
    """Return an objective to its manager with feedback."""
    if not feedback.strip():
        fail("feedback must say what still needs work")

    async def body(context: Context) -> Task:
        async with context.sessions() as db:
            task = await db.get(Task, task_id)
            if task is None:
                raise work.WorkError(f"no task {task_id}")
            await owner_decide(db, context.clock, task, accept=False, feedback=feedback)
            await db.commit()
            return task

    task = execute(body)
    typer.echo(f"task {task.id}: returned to agent {task.assignee_id}")


@task_app.command("merge")
def task_merge(
    task_id: Annotated[int, typer.Argument(help="The task's id.")],
    target: Annotated[str, typer.Option(help="The branch to merge into.")] = "main",
) -> None:
    """Request approval to merge a task's branch; the engine merges once it is approved."""

    async def body(context: Context) -> Approval:
        async with context.sessions() as db:
            return await work.request_merge(db, context.clock, task_id, target=target)

    approval = execute(body)
    payload = approval.payload
    typer.echo(
        f"approval {approval.id} {approval.status}: merge {payload['branch']} "
        f"({payload['commit'][:12]}) into {payload['target']}"
    )
