"""`project add`, `agent add` and `task add`: who works on what."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import typer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.adapters import default_registry as builtin_adapters
from labhq.cli.runtime import CliError, parse_usd, run_with_database
from labhq.clock import Clock, SystemClock
from labhq.db.enums import AgentStatus, WakeupSource
from labhq.db.models import Agent, Project, Task
from labhq.scheduler import EnqueueResult, Wakeup, enqueue
from labhq.worktrees.git import run_git

project_app = typer.Typer(help="Manage projects.", no_args_is_help=True)
agent_app = typer.Typer(help="Manage agents.", no_args_is_help=True)
task_app = typer.Typer(help="Manage tasks.", no_args_is_help=True)

BudgetOption = Annotated[
    str | None, typer.Option("--budget-usd", help="Monthly budget in USD, e.g. 5 or 0.25.")
]
ProjectOption = Annotated[str, typer.Option("--project", "-p", help="Project name.")]


async def project_named(db: AsyncSession, name: str) -> Project:
    project = await db.scalar(select(Project).where(Project.name == name))
    if project is None:
        raise CliError(f"no project named {name!r}")
    return project


async def agent_with_id(db: AsyncSession, agent_id: int) -> Agent:
    agent = await db.get(Agent, agent_id)
    if agent is None:
        raise CliError(f"no agent with id {agent_id}")
    return agent


def repository_root(path: Path) -> Path:
    """The top level of the git repository at `path`; worktrees are made from it."""
    if not path.is_dir():
        raise CliError(f"{path} is not a directory")
    return Path(run_git("rev-parse", "--show-toplevel", cwd=path).strip()).resolve()


async def add_project(
    db: AsyncSession, clock: Clock, name: str, repo: Path, budget_micros: int | None
) -> Project:
    now = clock.now()
    project = Project(
        name=name,
        repo_path=str(repository_root(repo)),
        budget_micros=budget_micros,
        created_at=now,
        updated_at=now,
    )
    db.add(project)
    await db.flush()
    return project


@dataclass(frozen=True)
class AgentSpec:
    role: str
    title: str
    adapter: str
    reports_to: int | None = None
    budget_micros: int | None = None
    config: dict[str, Any] | None = None


async def add_agent(db: AsyncSession, clock: Clock, project: Project, spec: AgentSpec) -> Agent:
    if spec.adapter not in builtin_adapters.adapter_keys():
        known = ", ".join(builtin_adapters.adapter_keys())
        raise CliError(f"no adapter {spec.adapter!r}; known adapters: {known}")
    if spec.reports_to is not None:
        manager = await agent_with_id(db, spec.reports_to)
        if manager.project_id != project.id:
            raise CliError(f"agent {manager.id} is not in project {project.name!r}")
    now = clock.now()
    agent = Agent(
        project_id=project.id,
        role=spec.role,
        title=spec.title,
        reports_to=spec.reports_to,
        adapter=spec.adapter,
        config=spec.config or {},
        budget_micros=spec.budget_micros,
        # The operator adding an agent at the CLI is the approval plan §5 rule 4 asks for.
        status=AgentStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    db.add(agent)
    await db.flush()
    return agent


@dataclass(frozen=True)
class TaskSpec:
    title: str
    description: str = ""
    priority: int = 0
    assignee_id: int | None = None


async def add_task(
    db: AsyncSession, clock: Clock, project: Project, spec: TaskSpec
) -> tuple[Task, EnqueueResult | None]:
    """Create a task; an assignee is woken up through the scheduler's assignment source."""
    if spec.assignee_id is not None:
        assignee = await agent_with_id(db, spec.assignee_id)
        if assignee.project_id != project.id:
            raise CliError(f"agent {assignee.id} is not in project {project.name!r}")
    now = clock.now()
    task = Task(
        project_id=project.id,
        title=spec.title,
        description=spec.description,
        priority=spec.priority,
        assignee_id=spec.assignee_id,
        created_at=now,
        updated_at=now,
    )
    db.add(task)
    await db.flush()
    if spec.assignee_id is None:
        return task, None
    wakeup = Wakeup(
        agent_id=spec.assignee_id,
        source=WakeupSource.ASSIGNMENT,
        idempotency_key=f"assignment:task:{task.id}:agent:{spec.assignee_id}",
        task_id=task.id,
        reason="assigned at the CLI",
    )
    return task, await enqueue(db, wakeup, clock)


def parse_config(text: str | None) -> dict[str, Any]:
    if text is None:
        return {}
    value = json.loads(text)
    if not isinstance(value, dict):
        raise CliError("--config must be a JSON object")
    return value


@project_app.command("add")
def project_add(
    name: Annotated[str, typer.Argument(help="Unique project name.")],
    repo: Annotated[Path, typer.Option("--repo", help="Path to the project's git repository.")],
    budget_usd: BudgetOption = None,
) -> None:
    """Register a project and the git repository its agents work in."""

    async def job(sessions: async_sessionmaker[AsyncSession]) -> None:
        budget = parse_usd(budget_usd)
        async with sessions() as db:
            project = await add_project(db, SystemClock(), name, repo, budget)
            await db.commit()
        typer.echo(f"project {project.id} {project.name} at {project.repo_path}")

    run_with_database(job)


@agent_app.command("add")
def agent_add(
    project: ProjectOption,
    role: Annotated[str, typer.Option(help="Role, e.g. manager or worker.")],
    adapter: Annotated[str, typer.Option(help="Registered adapter key, e.g. claude or fake.")],
    title: Annotated[str | None, typer.Option(help="Display title; defaults to the role.")] = None,
    reports_to: Annotated[
        int | None, typer.Option("--reports-to", help="Id of the agent this one reports to.")
    ] = None,
    budget_usd: BudgetOption = None,
    config: Annotated[
        str | None, typer.Option(help='Agent config as a JSON object, e.g. {"model": "..."}.')
    ] = None,
) -> None:
    """Add an active agent to a project."""

    async def job(sessions: async_sessionmaker[AsyncSession]) -> None:
        spec = AgentSpec(
            role=role,
            title=title or role.capitalize(),
            adapter=adapter,
            reports_to=reports_to,
            budget_micros=parse_usd(budget_usd),
            config=parse_config(config),
        )
        async with sessions() as db:
            agent = await add_agent(db, SystemClock(), await project_named(db, project), spec)
            await db.commit()
        typer.echo(f"agent {agent.id} {agent.title} ({agent.role}, {agent.adapter})")

    run_with_database(job)


@task_app.command("add")
def task_add(
    project: ProjectOption,
    title: Annotated[str, typer.Option(help="What the task is about.")],
    description: Annotated[str, typer.Option(help="Details for the agent.")] = "",
    priority: Annotated[int, typer.Option(help="Higher runs first.")] = 0,
    assignee: Annotated[
        int | None, typer.Option(help="Id of the agent to assign; wakes it up.")
    ] = None,
) -> None:
    """Add a task to a project, optionally assigned to an agent."""
    spec = TaskSpec(title=title, description=description, priority=priority, assignee_id=assignee)

    async def job(sessions: async_sessionmaker[AsyncSession]) -> None:
        async with sessions() as db:
            task, wakeup = await add_task(db, SystemClock(), await project_named(db, project), spec)
            await db.commit()
        typer.echo(f"task {task.id} {task.title}")
        if wakeup is not None:
            typer.echo(f"wakeup {wakeup.request.id} {wakeup.outcome} for agent {assignee}")

    run_with_database(job)
