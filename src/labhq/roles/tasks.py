"""`create_task` and `assign_task` for managers and leads, over `labhq.work`.

Scope is the caller's: its own project, and only agents below it in the hierarchy. A
manager's team is its whole project; a lead's is the members who report to it. Both are
`team_of` the caller, so the rule is one rule, not a branch per role.
"""

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.agenttools import AgentToolSpec, ToolContext
from labhq.db.enums import TaskStatus
from labhq.db.models import Agent, Task
from labhq.hierarchy import LEAD, MANAGER, team_of
from labhq.roles.common import refusing
from labhq.scheduler import enqueue
from labhq.work import WorkError, add_task, assignment, find_agent

SCOPED_ROLES = frozenset({MANAGER, LEAD})
CLOSED = frozenset({TaskStatus.DONE, TaskStatus.CANCELLED})


class CreateTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=300)
    description: str = ""
    priority: int = 0
    assignee: int | None = Field(default=None, description="A member of your team, by id.")


class AssignTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: int = Field(description="The task's id; it must belong to your project.")
    agent: int = Field(description="The member of your team who does it, by id.")


def _reason(caller: Agent) -> str:
    return f"assigned by {caller.title} (agent {caller.id})"


def _caller_project(caller: Agent) -> int:
    if caller.project_id is None:
        raise WorkError(f"agent {caller.id} belongs to no project")
    return caller.project_id


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
        project_id = _caller_project(caller)
        if arguments.assignee is not None:
            await check_in_team(db, caller, arguments.assignee)
        task = await add_task(
            db,
            context.clock,
            project=str(project_id),
            title=arguments.title,
            description=arguments.description,
            assignee=arguments.assignee,
            priority=arguments.priority,
            reason=_reason(caller),
        )
        await db.commit()
    assigned = f", assigned to agent {task.assignee_id}" if task.assignee_id else ""
    return f"Task #{task.id} created{assigned}."


async def assign_task(context: ToolContext, arguments: AssignTask) -> str:
    async with context.sessions() as db:
        caller = await db.get_one(Agent, context.agent_id)
        project_id = _caller_project(caller)
        task = await db.get(Task, arguments.task)
        if task is None or task.project_id != project_id:
            raise WorkError(f"task {arguments.task} is not in your project")
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
            name="create_task",
            description=(
                "Create a task in your project, optionally assigned to a member of your team."
            ),
            input_model=CreateTask,
            roles=SCOPED_ROLES,
            read_only=False,
            handler=refusing(create_task),
        ),
        AgentToolSpec(
            name="assign_task",
            description="Give a task of your project to a member of your team; it wakes them.",
            input_model=AssignTask,
            roles=SCOPED_ROLES,
            read_only=False,
            handler=refusing(assign_task),
        ),
    ]
