"""Create a department, appoint its head and give it tasks.

Functions add rows and flush; the caller owns the transaction and commits. The CEO does all
of this without asking (issue #171); the team cap and the budget ceiling still bind it, in
`labhq.hierarchy` and `labhq.ceoorg.budget`.
"""

import re
from collections.abc import Collection
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.adapters import UnknownAdapterError
from labhq.agenttools.registry import TOOLS_CONFIG_KEY
from labhq.clock import Clock
from labhq.db.enums import AgentStatus, DepartmentStatus, TaskStatus
from labhq.db.models import Agent, Department, Task
from labhq.departments.kinds import DepartmentKind, default_kinds
from labhq.hierarchy.team import DEPARTMENT_KEY
from labhq.scheduler import enqueue
from labhq.work import OPERATOR_REASON, WorkError, assignment, find_agent
from labhq.work.deliverables import default_deliverables

DEPARTMENTS_DIRECTORY = "departments"
CLOSED = frozenset({TaskStatus.DONE, TaskStatus.CANCELLED})
_SLUG = re.compile(r"[^a-z0-9]+")


def kind_named(key: str) -> DepartmentKind:
    if key not in default_kinds:
        raise WorkError(f"no department kind {key!r}; known: {', '.join(default_kinds)}")
    return default_kinds.get(key)


def folder_for(data_dir: Path, name: str) -> Path:
    slug = _SLUG.sub("-", name.lower()).strip("-")
    if not slug:
        raise WorkError(f"{name!r} cannot name a folder: use letters or digits")
    return data_dir / DEPARTMENTS_DIRECTORY / slug


async def find_department(db: AsyncSession, reference: str) -> Department:
    """A department by numeric id or by name."""
    query = select(Department).where(Department.name == reference)
    if reference.isdigit():
        query = select(Department).where(Department.id == int(reference))
    department = await db.scalar(query)
    if department is None:
        raise WorkError(f"no department {reference!r}")
    return department


def head_config(kind: DepartmentKind, name: str, folder: Path) -> dict[str, object]:
    """The head's config: the kind's own, plus what lets its prompt and tools find it."""
    config: dict[str, object] = dict(kind.head_config)
    if kind.tags_agents:
        config[DEPARTMENT_KEY] = {"kind": kind.key, "name": name, "folder": str(folder)}
        config[TOOLS_CONFIG_KEY] = sorted(kind.default_tools)
    return config


async def create_department(
    db: AsyncSession,
    clock: Clock,
    *,
    adapters: Collection[str],
    ceo: Agent,
    data_dir: Path,
    name: str,
    kind: str,
    adapter: str,
    head_title: str | None = None,
) -> tuple[Department, Agent]:
    """A department of a registered kind and its head, active at once, reporting to the CEO."""
    chosen = kind_named(kind)
    if adapter not in adapters:
        raise UnknownAdapterError(f"no adapter registered as {adapter!r}")
    if await db.scalar(select(Department.id).where(Department.name == name)) is not None:
        raise WorkError(f"a department named {name!r} already exists")
    folder = folder_for(data_dir, name)
    folder.mkdir(parents=True, exist_ok=True)
    now = clock.now()
    department = Department(
        name=name, kind=chosen.key, folder=str(folder), created_at=now, updated_at=now
    )
    db.add(department)
    await db.flush()
    head = Agent(
        project_id=None,
        department_id=department.id,
        role=chosen.head_role,
        title=head_title or f"{name} head",
        reports_to=ceo.id,
        adapter=adapter,
        config=head_config(chosen, name, folder),
        status=AgentStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    db.add(head)
    await db.flush()
    department.head_agent_id = head.id
    return department, head


async def department_of(db: AsyncSession, agent: Agent) -> Department:
    if agent.department_id is None:
        raise WorkError(f"agent {agent.id} belongs to no department")
    return await db.get_one(Department, agent.department_id)


async def add_department_task(
    db: AsyncSession,
    clock: Clock,
    department: Department,
    *,
    title: str,
    deliverable: str,
    description: str = "",
    assignee: int | None = None,
    priority: int = 0,
    parent_id: int | None = None,
    reason: str = OPERATOR_REASON,
) -> Task:
    """A task of a department, never of a project: the check constraint holds the same line."""
    kind = kind_named(department.kind)
    if deliverable not in default_deliverables or deliverable not in kind.deliverables:
        raise WorkError(
            f"a {kind.key} department delivers {', '.join(sorted(kind.deliverables))}, "
            f"not {deliverable!r}"
        )
    if department.status is not DepartmentStatus.ACTIVE:
        raise WorkError(f"department {department.name} is {department.status}")
    if parent_id is not None:
        parent = await db.get(Task, parent_id)
        if parent is None or parent.department_id != department.id:
            raise WorkError(f"parent task {parent_id} is not in department {department.name!r}")
        if parent.status in CLOSED:
            raise WorkError(f"parent task {parent_id} is {parent.status}")
    if assignee is not None and (await find_agent(db, assignee)).department_id != department.id:
        raise WorkError(f"agent {assignee} does not belong to department {department.name!r}")
    now = clock.now()
    task = Task(
        project_id=None,
        department_id=department.id,
        parent_id=parent_id,
        title=title,
        description=description,
        deliverable=deliverable,
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
