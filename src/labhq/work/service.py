"""Projects, agents and tasks: who works on what, for every caller (CLI, Call Center).

Functions add rows and flush; the caller owns the transaction and commits. Errors an operator
or a voice caller can act on are `WorkError`s with a message that says what is wrong.
"""

from collections.abc import Collection
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.adapters import UnknownAdapterError
from labhq.clock import Clock
from labhq.db.enums import AgentStatus, WakeupSource
from labhq.db.models import Agent, Project, Task
from labhq.scheduler import Wakeup, enqueue
from labhq.worktrees import GitError
from labhq.worktrees.git import run_git

OPERATOR_REASON = "assigned by the operator"


class WorkError(RuntimeError):
    """A request about projects, agents or tasks that cannot be carried out as given."""


async def find_project(db: AsyncSession, reference: str) -> Project:
    """A project by numeric id or by name."""
    query = select(Project).where(Project.name == reference)
    if reference.isdigit():
        query = select(Project).where(Project.id == int(reference))
    project = await db.scalar(query)
    if project is None:
        raise WorkError(f"no project {reference!r}")
    return project


async def find_agent(db: AsyncSession, agent_id: int) -> Agent:
    agent = await db.get(Agent, agent_id)
    if agent is None:
        raise WorkError(f"no agent {agent_id}")
    return agent


def check_repository(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    try:
        run_git("rev-parse", "--verify", "HEAD", cwd=resolved)
    except (GitError, OSError) as error:
        raise WorkError(f"{resolved} is not a git repository with a commit") from error
    return resolved


async def add_project(
    db: AsyncSession, clock: Clock, *, name: str, repo: Path, budget: int | None
) -> Project:
    if await db.scalar(select(Project.id).where(Project.name == name)) is not None:
        raise WorkError(f"a project named {name!r} already exists")
    now = clock.now()
    project = Project(
        name=name, repo_path=str(repo), budget_micros=budget, created_at=now, updated_at=now
    )
    db.add(project)
    await db.flush()
    return project


async def add_agent(
    db: AsyncSession,
    clock: Clock,
    *,
    adapters: Collection[str],
    project: str,
    role: str,
    title: str,
    adapter: str,
    reports_to: int | None = None,
    config: dict[str, Any] | None = None,
    budget: int | None = None,
    status: AgentStatus = AgentStatus.PENDING_APPROVAL,
) -> Agent:
    if adapter not in adapters:
        raise UnknownAdapterError(f"no adapter registered as {adapter!r}")
    owner = await find_project(db, project)
    if reports_to is not None:
        await find_agent(db, reports_to)
    now = clock.now()
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
    await db.flush()
    return agent


def assignment(task: Task, agent_id: int, reason: str = OPERATOR_REASON) -> Wakeup:
    return Wakeup(
        agent_id=agent_id,
        source=WakeupSource.ASSIGNMENT,
        idempotency_key=f"assignment:task:{task.id}:agent:{agent_id}",
        task_id=task.id,
        reason=reason,
    )


async def add_task(
    db: AsyncSession,
    clock: Clock,
    *,
    project: str,
    title: str,
    description: str = "",
    assignee: int | None = None,
    priority: int = 0,
    reason: str = OPERATOR_REASON,
) -> Task:
    owner = await find_project(db, project)
    if assignee is not None and (await find_agent(db, assignee)).project_id != owner.id:
        raise WorkError(f"agent {assignee} does not belong to project {owner.name!r}")
    now = clock.now()
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
        await enqueue(db, assignment(task, assignee, reason), clock)
    return task
