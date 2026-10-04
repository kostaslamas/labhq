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
from labhq.adapters.kinds import choice_named
from labhq.clock import Clock
from labhq.db.enums import AgentStatus, TaskStatus, WakeupSource
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


def resolve_kind(
    kind: str | None, adapter: str | None, config: dict[str, Any] | None
) -> tuple[str | None, dict[str, Any]]:
    """The adapter and config an agent kind stands for; without a kind, what was given."""
    given = dict(config or {})
    if kind is None:
        return adapter, given
    choice = choice_named(kind)
    if adapter is not None and adapter != choice.adapter:
        raise WorkError(f"kind {kind!r} runs on adapter {choice.adapter!r}, not {adapter!r}")
    # The kind decides its own keys; the rest of the caller's config stays.
    return choice.adapter, {**given, **choice.config}


async def add_agent(
    db: AsyncSession,
    clock: Clock,
    *,
    adapters: Collection[str],
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
    adapter, config = resolve_kind(kind, adapter, config)
    if adapter is None:
        raise WorkError("name the agent's kind or its adapter")
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
        config=config,
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
    parent_id: int | None = None,
    reason: str = OPERATOR_REASON,
) -> Task:
    owner = await find_project(db, project)
    if parent_id is not None:
        parent = await db.get(Task, parent_id)
        if parent is None or parent.project_id != owner.id:
            raise WorkError(f"parent task {parent_id} is not in project {owner.name!r}")
        if parent.status in {TaskStatus.DONE, TaskStatus.CANCELLED}:
            raise WorkError(f"parent task {parent_id} is {parent.status}")
    if assignee is not None and (await find_agent(db, assignee)).project_id != owner.id:
        raise WorkError(f"agent {assignee} does not belong to project {owner.name!r}")
    now = clock.now()
    task = Task(
        project_id=owner.id,
        parent_id=parent_id,
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
