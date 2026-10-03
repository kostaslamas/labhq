"""`init`, `project add`, `agent add|approve` and `task add`: who works on what."""

from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated, Any

import typer
from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.adapters import UnknownAdapterError
from labhq.cli.context import CliError, Context, execute, fail, load_settings
from labhq.cli.engine import cli_adapters
from labhq.clock import Clock
from labhq.db.enums import AgentStatus, WakeupSource
from labhq.db.models import Agent, Project, Task
from labhq.money import usd_to_micros
from labhq.scheduler import Wakeup, enqueue
from labhq.worktrees import GitError
from labhq.worktrees.git import run_git

# Migrations ship with the source tree, next to `src/`; `labhq` runs from a checkout.
MIGRATIONS = Path(__file__).resolve().parents[3] / "migrations"

project_app = typer.Typer(help="Register git repositories as projects.", no_args_is_help=True)
agent_app = typer.Typer(help="Add agents and approve new ones.", no_args_is_help=True)
task_app = typer.Typer(help="Add tasks and assign them to agents.", no_args_is_help=True)


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


async def find_project(db: AsyncSession, reference: str) -> Project:
    """A project by numeric id or by name."""
    query = select(Project).where(Project.name == reference)
    if reference.isdigit():
        query = select(Project).where(Project.id == int(reference))
    project = await db.scalar(query)
    if project is None:
        raise CliError(f"no project {reference!r}")
    return project


async def find_agent(db: AsyncSession, agent_id: int) -> Agent:
    agent = await db.get(Agent, agent_id)
    if agent is None:
        raise CliError(f"no agent {agent_id}")
    return agent


def check_repository(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    try:
        run_git("rev-parse", "--verify", "HEAD", cwd=resolved)
    except (GitError, OSError) as error:
        raise CliError(f"{resolved} is not a git repository with a commit") from error
    return resolved


async def create_project(context: Context, name: str, repo: Path, budget: int | None) -> Project:
    now = context.clock.now()
    async with context.sessions() as db:
        if await db.scalar(select(Project.id).where(Project.name == name)) is not None:
            raise CliError(f"a project named {name!r} already exists")
        project = Project(
            name=name, repo_path=str(repo), budget_micros=budget, created_at=now, updated_at=now
        )
        db.add(project)
        await db.commit()
    return project


@project_app.command("add")
def project_add(
    name: Annotated[str, typer.Argument(help="A unique project name.")],
    repo: Annotated[Path, typer.Option(help="The project's git repository.")],
    budget_usd: Annotated[
        str | None, typer.Option(help="Monthly budget in USD, for example 25 or 2.50.")
    ] = None,
) -> None:
    """Register a git repository as a project."""

    async def body(context: Context) -> Project:
        return await create_project(context, name, check_repository(repo), parse_budget(budget_usd))

    project = execute(body)
    typer.echo(f"project {project.id} {project.name}: {project.repo_path}")


async def create_agent(
    context: Context,
    *,
    project: str,
    role: str,
    title: str,
    adapter: str,
    reports_to: int | None = None,
    config: dict[str, Any] | None = None,
    budget: int | None = None,
    status: AgentStatus = AgentStatus.PENDING_APPROVAL,
) -> Agent:
    if adapter not in cli_adapters().adapter_keys():
        raise UnknownAdapterError(f"no adapter registered as {adapter!r}")
    now = context.clock.now()
    async with context.sessions() as db:
        owner = await find_project(db, project)
        if reports_to is not None:
            await find_agent(db, reports_to)
        agent = Agent(
            project_id=owner.id,
            role=role,
            title=title,
            reports_to=reports_to,
            adapter=adapter,
            config=config or {},
            budget_micros=budget,
            status=status,
            created_at=now,
            updated_at=now,
        )
        db.add(agent)
        await db.commit()
    return agent


@agent_app.command("add")
def agent_add(
    project: Annotated[str, typer.Option(help="Project name or id.")],
    role: Annotated[str, typer.Option(help="The agent's role, for example manager or worker.")],
    title: Annotated[str, typer.Option(help="A human-readable title.")],
    adapter: Annotated[str, typer.Option(help="Adapter key: fake or claude.")] = "fake",
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
            adapter=adapter,
            reports_to=reports_to,
            budget=parse_budget(budget_usd),
        )

    agent = execute(body)
    typer.echo(f"agent {agent.id} {agent.title} ({agent.role}, {agent.adapter}): {agent.status}")


@agent_app.command("approve")
def agent_approve(agent_id: Annotated[int, typer.Argument(help="The agent's id.")]) -> None:
    """Approve a new agent, so the scheduler may start its runs."""

    async def body(context: Context) -> Agent:
        async with context.sessions() as db:
            agent = await find_agent(db, agent_id)
            if agent.status is not AgentStatus.PENDING_APPROVAL:
                raise CliError(f"agent {agent_id} is {agent.status}, not pending approval")
            agent.status = AgentStatus.ACTIVE
            agent.updated_at = context.clock.now()
            await db.commit()
        return agent

    agent = execute(body)
    typer.echo(f"agent {agent.id} {agent.title}: {agent.status}")


def assignment(task: Task, agent_id: int) -> Wakeup:
    return Wakeup(
        agent_id=agent_id,
        source=WakeupSource.ASSIGNMENT,
        idempotency_key=f"assignment:task:{task.id}:agent:{agent_id}",
        task_id=task.id,
        reason="assigned by the operator",
    )


async def create_task(
    context: Context,
    *,
    project: str,
    title: str,
    description: str = "",
    assignee: int | None = None,
    priority: int = 0,
) -> Task:
    clock: Clock = context.clock
    now = clock.now()
    async with context.sessions() as db:
        owner = await find_project(db, project)
        if assignee is not None and (await find_agent(db, assignee)).project_id != owner.id:
            raise CliError(f"agent {assignee} does not belong to project {owner.name!r}")
        task = Task(
            project_id=owner.id,
            title=title,
            description=description,
            assignee_id=assignee,
            priority=priority,
            created_at=now,
            updated_at=now,
        )
        db.add(task)
        await db.flush()
        if assignee is not None:
            await enqueue(db, assignment(task, assignee), clock)
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
