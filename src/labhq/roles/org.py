"""The CEO's tools and the manager's team proposal, over `labhq.hierarchy` (#72).

Neither decides anything: a new manager waits for a light approval and a team for a heavy
one (plan §5, rules 4 and 7). The agent is the run's, never an argument.
"""

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from labhq.agenttools import AgentToolSpec, ToolContext
from labhq.agenttools.whoami import NoArguments
from labhq.ceoorg.record import record_action
from labhq.ceosessions import ceo_session_name
from labhq.db.enums import AgentStatus, RunStatus
from labhq.db.models import Agent, Project, Run, RunEvent
from labhq.hierarchy import CEO, MANAGER, ProposedMember
from labhq.roles.common import RoleServices, refusing
from labhq.work import WorkError, add_task, find_project


class AssignManager(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: str = Field(min_length=1, description="The project's name or numeric id.")
    title: str | None = Field(default=None, max_length=200)


class ProposeTeam(BaseModel):
    model_config = ConfigDict(extra="forbid")

    members: list[ProposedMember] = Field(min_length=1)


class DelegateTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: str = Field(min_length=1, description="Project name or numeric id.")
    title: str = Field(min_length=1, max_length=300)
    description: str = ""
    priority: int = 0


async def list_projects(context: ToolContext, arguments: NoArguments) -> str:
    async with context.sessions() as db:
        projects = list(await db.scalars(select(Project).order_by(Project.id)))
        managers = await db.scalars(
            select(Agent).where(Agent.role == MANAGER, Agent.status != AgentStatus.RETIRED)
        )
        by_project = {manager.project_id: manager for manager in managers}
    if not projects:
        return "There are no projects."
    lines = []
    for project in projects:
        manager = by_project.get(project.id)
        led = (
            f"manager agent {manager.id} ({manager.status})"
            if manager is not None
            else "NO MANAGER: give it one with `assign_manager`, `adopt_session` or "
            "`assign_saved_session`"
        )
        lines.append(f"- {project.name} (id {project.id}, {project.status}): {led}")
    return "\n".join(lines)


async def list_agent_sessions(context: ToolContext, arguments: NoArguments) -> str:
    """Durable run status and attachable tmux names, without exposing CLI session IDs."""
    async with context.sessions() as db:
        agents = list(await db.scalars(select(Agent).order_by(Agent.id)))
        by_id = {agent.id: agent for agent in agents}
        runs = list(await db.scalars(select(Run).order_by(Run.id.desc())))
        latest = {run.agent_id: run for run in reversed(runs)}
        ceo_panes: dict[int, set[str]] = {}
        for run in runs:
            if run.adapter != "tmux" or by_id[run.agent_id].role != CEO:
                continue
            event = await db.scalar(
                select(RunEvent).where(RunEvent.run_id == run.id, RunEvent.kind == "agent")
            )
            name = event.payload.get("kind") if event is not None else None
            stored_kind = (run.session_id_after or "").partition(":")[0]
            kind = name if isinstance(name, str) else stored_kind
            if kind:
                ceo_panes.setdefault(run.agent_id, set()).add(ceo_session_name(kind))
    if not agents:
        return "There are no agents."
    lines = []
    for agent in agents:
        recent = latest.get(agent.id)
        if recent is None:
            lines.append(f"- agent {agent.id} ({agent.role}, {agent.title}): no runs")
            continue
        pane = ""
        if agent.role == CEO and ceo_panes.get(agent.id):
            pane = f", tmux names {', '.join(sorted(ceo_panes[agent.id]))}"
        elif recent.adapter == "tmux" and recent.status == RunStatus.RUNNING:
            pane = f", tmux run-{recent.id}"
        lines.append(
            f"- agent {agent.id} ({agent.role}, {agent.title}): "
            f"run {recent.id} {recent.status}{pane}"
        )
    return "\n".join(lines)


def ceo_tools(services: RoleServices) -> list[AgentToolSpec]:
    @refusing
    async def delegate_task(context: ToolContext, arguments: DelegateTask) -> str:
        async with context.sessions() as db:
            project = await find_project(db, arguments.project)
            manager = await db.scalar(
                select(Agent).where(
                    Agent.project_id == project.id,
                    Agent.role == MANAGER,
                    Agent.status == AgentStatus.ACTIVE,
                )
            )
            if manager is None:
                raise WorkError(f"project {project.name} has no active manager")
            task = await add_task(
                db,
                context.clock,
                project=str(project.id),
                title=arguments.title,
                description=arguments.description,
                priority=arguments.priority,
                assignee=manager.id,
                reason=f"delegated by CEO agent {context.agent_id}",
            )
            await db.commit()
        return f"Task #{task.id} delegated to {manager.title}; review will return to the CEO."

    @refusing
    async def assign_manager(context: ToolContext, arguments: AssignManager) -> str:
        # The owner lets the CEO assign managers unasked, so the manager starts active.
        assignment = await services.ceo_hierarchy(context).assign_manager(
            arguments.project, title=arguments.title
        )
        await record_action(
            context,
            "assign_manager",
            {"project": arguments.project, "manager": assignment.manager.id},
        )
        return f"Agent {assignment.manager.id} now manages {arguments.project}."

    return [
        AgentToolSpec(
            name="list_projects",
            description="List every project with its status and manager.",
            input_model=NoArguments,
            roles=frozenset({CEO}),
            read_only=True,
            handler=list_projects,
        ),
        AgentToolSpec(
            name="list_agent_sessions",
            description="List agents, their latest run status and CEO tmux session names.",
            input_model=NoArguments,
            roles=frozenset({CEO}),
            read_only=True,
            handler=list_agent_sessions,
        ),
        AgentToolSpec(
            name="assign_manager",
            description=(
                "Give a project without a manager its manager, reporting to you. No approval."
            ),
            input_model=AssignManager,
            roles=frozenset({CEO}),
            read_only=False,
            handler=assign_manager,
        ),
        AgentToolSpec(
            name="delegate_task",
            description="Give a project objective to its active manager and track its review.",
            input_model=DelegateTask,
            roles=frozenset({CEO}),
            read_only=False,
            handler=delegate_task,
        ),
    ]


def manager_tools(services: RoleServices) -> list[AgentToolSpec]:
    @refusing
    async def propose_team(context: ToolContext, arguments: ProposeTeam) -> str:
        approval = await services.hierarchy(context).propose_team(
            context.agent_id, arguments.members
        )
        return (
            f"Team of {len(arguments.members)} proposed as A{approval.id} "
            f"({approval.risk_class}); no agent exists until the owner approves it."
        )

    return [
        AgentToolSpec(
            name="propose_team",
            description=(
                "Propose team members (leads and workers) for your project. Each member has a "
                "key, a role, a title, an adapter and optionally the key it reports to; "
                "without one it reports to you. The owner approves the team as a whole."
            ),
            input_model=ProposeTeam,
            roles=frozenset({MANAGER}),
            read_only=False,
            handler=propose_team,
        )
    ]
