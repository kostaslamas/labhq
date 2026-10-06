"""`create_task` and `assign_task` for managers and leads, over `labhq.work`.

Scope is the caller's: its own project, and only agents below it in the hierarchy. A
manager's team is its whole project; a lead's is the members who report to it. Both are
`team_of` the caller, so the rule is one rule, not a branch per role.
"""

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.agenttools import AgentToolSpec, ToolContext
from labhq.db.enums import TaskStatus
from labhq.db.models import Agent, Comment, Run, Task
from labhq.departments import add_department_task, department_of
from labhq.hierarchy import CEO, HEAD, LEAD, MANAGER, WORKER, team_of
from labhq.roles.common import refusing
from labhq.scheduler import enqueue
from labhq.work import WorkError, add_task, assignment, find_agent
from labhq.work.deliverables import REPORT
from labhq.work.progress import report_task as report_progress
from labhq.work.progress import review_task as review_progress

SCOPED_ROLES = frozenset({MANAGER, LEAD, HEAD})
CLOSED = frozenset({TaskStatus.DONE, TaskStatus.CANCELLED})


class CreateTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=300)
    description: str = ""
    priority: int = 0
    assignee: int | None = Field(default=None, description="A member of your team, by id.")
    parent: int | None = Field(
        default=None, description="Task you are splitting; defaults to the task of this run."
    )
    deliverable: str | None = Field(
        default=None,
        description="In a department: document, report or decision. Default: the parent's.",
    )


class AssignTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: int = Field(description="The task's id; it must belong to your project.")
    agent: int = Field(description="The member of your team who does it, by id.")


class TaskReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: int


class ReportTask(TaskReference):
    summary: str = Field(min_length=1)
    blocked: bool = False


class ReviewTask(TaskReference):
    accept: bool
    feedback: str = Field(min_length=1)


def _reason(caller: Agent) -> str:
    return f"assigned by {caller.title} (agent {caller.id})"


def _caller_project(caller: Agent) -> int:
    if caller.project_id is None:
        raise WorkError(f"agent {caller.id} belongs to no project")
    return caller.project_id


def _scope_word(caller: Agent) -> str:
    return "department" if caller.department_id is not None else "project"


def in_scope(task: Task, caller: Agent) -> bool:
    """A task is in the caller's scope when it is in the caller's project or department."""
    if caller.project_id is None and caller.department_id is None:
        return False
    return (task.project_id, task.department_id) == (caller.project_id, caller.department_id)


async def check_in_team(db: AsyncSession, caller: Agent, agent_id: int) -> Agent:
    """The agent, if it is below `caller`; anything else is refused."""
    team = {member.id: member for member in await team_of(db, caller)}
    member = team.get(agent_id)
    if member is None:
        await find_agent(db, agent_id)
        raise WorkError(f"agent {agent_id} is not in your team")
    return member


async def create_task(context: ToolContext, arguments: CreateTask) -> str:
    async with context.sessions() as db:
        caller = await db.get_one(Agent, context.agent_id)
        if arguments.assignee is not None:
            await check_in_team(db, caller, arguments.assignee)
        parent_id = arguments.parent
        if parent_id is None and context.run_id is not None:
            run = await db.get(Run, context.run_id)
            parent_id = run.task_id if run is not None else None
        parent = await db.get(Task, parent_id) if parent_id is not None else None
        if parent is not None and not (
            in_scope(parent, caller) and parent.assignee_id == caller.id
        ):
            raise WorkError(
                f"parent task {parent_id} is not assigned to you in this {_scope_word(caller)}"
            )
        if caller.department_id is not None:
            department = await department_of(db, caller)
            task = await add_department_task(
                db,
                context.clock,
                department,
                title=arguments.title,
                description=arguments.description,
                deliverable=arguments.deliverable or (parent.deliverable if parent else REPORT),
                assignee=arguments.assignee,
                priority=arguments.priority,
                parent_id=parent_id,
                reason=_reason(caller),
            )
        else:
            task = await add_task(
                db,
                context.clock,
                project=str(_caller_project(caller)),
                title=arguments.title,
                description=arguments.description,
                assignee=arguments.assignee,
                priority=arguments.priority,
                parent_id=parent_id,
                reason=_reason(caller),
            )
        await db.commit()
    assigned = f", assigned to agent {task.assignee_id}" if task.assignee_id else ""
    parent_suffix = f", under task #{task.parent_id}" if task.parent_id else ""
    return f"Task #{task.id} created{assigned}{parent_suffix}."


async def task_overview(context: ToolContext, arguments: TaskReference) -> str:
    async with context.sessions() as db:
        caller = await db.get_one(Agent, context.agent_id)
        task = await db.get(Task, arguments.task)
        if task is None or (caller.role != CEO and not in_scope(task, caller)):
            raise WorkError(f"task {arguments.task} is outside your scope")
        if caller.role == WORKER and task.assignee_id != caller.id:
            raise WorkError(f"task {arguments.task} is outside your scope")
        children = list(
            await db.scalars(select(Task).where(Task.parent_id == task.id).order_by(Task.id))
        )
        comments = list(
            await db.scalars(
                select(Comment)
                .where(Comment.task_id == task.id)
                .order_by(Comment.id.desc())
                .limit(5)
            )
        )
    lines = [
        f"Task #{task.id}: {task.title} [{task.status}], assignee {task.assignee_id}, "
        f"parent {task.parent_id}.",
        task.description,
        "Children: " + (", ".join(f"#{c.id} {c.title} [{c.status}]" for c in children) or "none"),
        "Recent reports: "
        + ("; ".join(f"agent {c.author_agent_id}: {c.body}" for c in comments) or "none"),
    ]
    return "\n".join(line for line in lines if line)


async def report_task(context: ToolContext, arguments: ReportTask) -> str:
    async with context.sessions() as db:
        task = await db.get(Task, arguments.task)
        if task is None:
            raise WorkError(f"no task {arguments.task}")
        await report_progress(
            db,
            context.clock,
            task,
            context.agent_id,
            summary=arguments.summary,
            blocked=arguments.blocked,
        )
        await db.commit()
    return f"Task #{task.id} reported as {task.status}; its reviewer was woken."


async def review_task(context: ToolContext, arguments: ReviewTask) -> str:
    async with context.sessions() as db:
        caller = await db.get_one(Agent, context.agent_id)
        task = await db.get(Task, arguments.task)
        if task is None:
            raise WorkError(f"no task {arguments.task}")
        await review_progress(
            db,
            context.clock,
            task,
            context.agent_id,
            accept=arguments.accept,
            feedback=arguments.feedback,
        )
        await db.commit()
    if (
        caller.role == CEO
        and arguments.accept
        and task.parent_id is None
        and task.department_id is None
    ):
        return f"Task #{task.id} recommended to the owner; only the owner can close it."
    return f"Task #{task.id} is {task.status}."


async def assign_task(context: ToolContext, arguments: AssignTask) -> str:
    async with context.sessions() as db:
        caller = await db.get_one(Agent, context.agent_id)
        task = await db.get(Task, arguments.task)
        if task is None or not in_scope(task, caller):
            raise WorkError(f"task {arguments.task} is not in your {_scope_word(caller)}")
        if task.status in CLOSED:
            raise WorkError(f"task {task.id} is {task.status}")
        if task.checkout_run_id is not None:
            raise WorkError(f"task {task.id} is being worked on by run {task.checkout_run_id}")
        member = await check_in_team(db, caller, arguments.agent)
        task.assignee_id = member.id
        task.updated_at = context.clock.now()
        await enqueue(db, assignment(task, member.id, _reason(caller)), context.clock)
        await db.commit()
    return f"Task #{task.id} assigned to agent {member.id} ({member.title})."


def task_tools() -> list[AgentToolSpec]:
    return [
        AgentToolSpec(
            name="task_overview",
            description="Read a task, its children and recent reports.",
            input_model=TaskReference,
            roles=frozenset({CEO, MANAGER, LEAD, WORKER, HEAD}),
            read_only=True,
            handler=refusing(task_overview),
        ),
        AgentToolSpec(
            name="create_task",
            description=(
                "Create a task in your project or department, optionally assigned to a member of "
                "your team."
            ),
            input_model=CreateTask,
            roles=SCOPED_ROLES,
            read_only=False,
            handler=refusing(create_task),
        ),
        AgentToolSpec(
            name="assign_task",
            description="Give a task of your scope to a member of your team; it wakes them.",
            input_model=AssignTask,
            roles=SCOPED_ROLES,
            read_only=False,
            handler=refusing(assign_task),
        ),
        AgentToolSpec(
            name="report_task",
            description="Report your assigned task ready for review, or blocked, with a summary.",
            input_model=ReportTask,
            roles=frozenset({MANAGER, LEAD, WORKER, HEAD}),
            read_only=False,
            handler=refusing(report_task),
        ),
        AgentToolSpec(
            name="review_task",
            description="Accept a direct report's reviewed task, or return it with feedback.",
            input_model=ReviewTask,
            roles=frozenset({CEO, MANAGER, LEAD, HEAD}),
            read_only=False,
            handler=refusing(review_task),
        ),
    ]
