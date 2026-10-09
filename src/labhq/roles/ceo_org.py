"""The CEO runs the organisation: add and adopt projects, staff teams, set priorities and budgets.

The owner lets the CEO do all of this without asking (issue #168). Two things stay the
owner's: executing a merge or a push needs a passkey, and a budget cannot pass the owner's
ceiling. Every tool records the CEO as its actor (`labhq.ceoorg.record`).
"""

import asyncio
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from labhq.adapters.tmux import default_kinds
from labhq.agenttools import AgentToolSpec, ToolContext
from labhq.ceoorg.background import spawn
from labhq.ceoorg.budget import BudgetScope, set_budget
from labhq.ceoorg.discover import (
    Discovery,
    check_root,
    render,
    resolve_roots,
    saved_sessions,
    scan_folders,
    within,
)
from labhq.ceoorg.meetings import CEO_CONFIRMATION
from labhq.ceoorg.meetings import start_meeting as start_ceo_meeting
from labhq.ceoorg.record import actor, record_action
from labhq.db.enums import TaskStatus
from labhq.db.models import Approval, Project, Task
from labhq.hierarchy import CEO, ProposedMember
from labhq.roles.common import RoleServices, refusing
from labhq.work import (
    WorkError,
    add_project,
    check_project_directory,
    find_project,
    request_merge,
)

CLOSED = frozenset({TaskStatus.DONE, TaskStatus.CANCELLED})


class DiscoverProjects(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root: str | None = Field(
        default=None, description="A folder inside the allowed roots. Default: all the roots."
    )


class AddProject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    path: str = Field(min_length=1, description="An existing folder or repository, absolute.")


class AdoptSession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: str = Field(min_length=1, description="The project's name or numeric id.")
    pid: int = Field(gt=0, description="The process id `discover_projects` listed.")


class AssignSavedSession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: str = Field(min_length=1, description="The project's name or numeric id.")
    kind: str = Field(min_length=1, description="The CLI kind, for example claude-code.")
    session_id: str = Field(min_length=1)


class StaffTeam(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manager: int = Field(description="The project manager's agent id.")
    members: list[ProposedMember] = Field(min_length=1)


class CreateAgent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manager: int = Field(description="The project manager's agent id.")
    role: str
    title: str = Field(min_length=1, max_length=200)
    adapter: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        description="Default: the role's adapter; workers run headless.",
    )
    reports_to: int | None = Field(
        default=None, description="A member of the manager's team; default the manager."
    )


class RequestMerge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: int


class StartMeeting(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: str = Field(min_length=1, description="The project's name or numeric id.")
    kind: str = Field(default="standup", description="standup, planning or review.")


class SetPriority(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: int
    priority: int


class SetBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: BudgetScope
    id: int | str = Field(description="An agent's id, or a project's or department's name or id.")
    micros: int = Field(gt=0, description="The budget in micro-USD (1 USD = 1,000,000).")


def ceo_org_tools(services: RoleServices) -> list[AgentToolSpec]:
    @refusing
    async def discover_projects(context: ToolContext, arguments: DiscoverProjects) -> str:
        settings = services.ceo_settings()
        roots = resolve_roots(services.browse_roots())
        starts = check_root(Path(arguments.root) if arguments.root else None, roots)
        async with context.sessions() as db:
            projects = list(await db.scalars(select(Project)))
        registered = {Path(project.repo_path).resolve(): project.name for project in projects}
        folders, truncated = await asyncio.to_thread(
            scan_folders,
            starts,
            roots,
            depth=settings.discovery_depth,
            limit=settings.discovery_limit,
            registered=registered,
        )
        running = [
            agent
            for agent in await services.adoptions(context).discover()
            if any(within(agent.cwd.resolve(), [start]) for start in starts)
        ]
        saved = await asyncio.to_thread(
            saved_sessions, [folder.path for folder in folders], settings.discovery_limit
        )
        return render(Discovery(tuple(folders), tuple(running), tuple(saved), truncated))

    @refusing
    async def add_project_tool(context: ToolContext, arguments: AddProject) -> str:
        roots = resolve_roots(services.browse_roots())
        folder = check_project_directory(Path(arguments.path))
        if within(folder, roots) is None:
            raise WorkError(f"{folder} is outside the allowed roots; use `discover_projects`")
        async with context.sessions() as db:
            project = await add_project(
                db, context.clock, name=arguments.name, repo=folder, budget=None
            )
            await db.commit()
        await record_action(
            context,
            "add_project",
            {"project": project.id, "name": project.name, "path": str(folder)},
        )
        try:
            assignment = await services.ceo_hierarchy(context).assign_manager(str(project.id))
        except (WorkError, ValueError) as error:
            return (
                f"Project {project.name} (id {project.id}) added, but it has no manager yet: "
                f"{error}. Fix that, then call `assign_manager` or `adopt_session`."
            )
        await record_action(
            context, "assign_manager", {"project": project.id, "manager": assignment.manager.id}
        )
        return (
            f"Project {project.name} (id {project.id}) added; "
            f"agent {assignment.manager.id} manages it."
        )

    async def decide(context: ToolContext, approval: Approval, name: str) -> None:
        """Decide a light adoption as the CEO and let the engine execute it unattended."""
        approvals = services.approvals(context)
        spawn(
            approvals.approve(
                approval.id, decider=actor(context.agent_id), confirmation=CEO_CONFIRMATION
            ),
            name=name,
        )

    @refusing
    async def adopt_session(context: ToolContext, arguments: AdoptSession) -> str:
        async with context.sessions() as db:
            project = await find_project(db, arguments.project)
        request = await services.adoptions(context).request(
            arguments.pid, project=project.name, requested_by=context.agent_id
        )
        await decide(context, request.approval, f"adopt-{request.approval.id}")
        await record_action(
            context,
            "adopt_session",
            {"project": project.id, "pid": arguments.pid, "approval": request.approval.id},
        )
        return (
            f"Adopting process {arguments.pid} as manager of {project.name}: approval "
            f"A{request.approval.id} is decided, and it takes over once its turn ends."
        )

    @refusing
    async def assign_saved_session(context: ToolContext, arguments: AssignSavedSession) -> str:
        try:
            default_kinds.get(arguments.kind)
            async with context.sessions() as db:
                project = await find_project(db, arguments.project)
            approval = await services.adoptions(context).request_saved(
                kind=arguments.kind, session_id=arguments.session_id, project=project
            )
        except LookupError as error:
            raise WorkError(str(error)) from None
        await decide(context, approval, f"adopt-saved-{approval.id}")
        await record_action(
            context,
            "assign_saved_session",
            {"project": project.id, "kind": arguments.kind, "approval": approval.id},
        )
        return (
            f"Resuming {arguments.kind} session as manager of {project.name}: approval "
            f"A{approval.id} is decided."
        )

    @refusing
    async def staff_team(context: ToolContext, arguments: StaffTeam) -> str:
        ids = await services.ceo_hierarchy(context).staff_team(arguments.manager, arguments.members)
        await record_action(context, "staff_team", {"manager": arguments.manager, "agents": ids})
        created = ", ".join(f"{key}=agent {agent_id}" for key, agent_id in ids.items())
        return f"Team created under agent {arguments.manager}: {created}."

    @refusing
    async def create_agent(context: ToolContext, arguments: CreateAgent) -> str:
        agent = await services.ceo_hierarchy(context).create_agent(
            arguments.manager,
            role=arguments.role,
            title=arguments.title,
            adapter=arguments.adapter,
            reports_to=arguments.reports_to,
        )
        await record_action(
            context, "create_agent", {"manager": arguments.manager, "agent": agent.id}
        )
        return f"Agent {agent.id} ({agent.title}) created, reporting to agent {agent.reports_to}."

    @refusing
    async def request_merge_tool(context: ToolContext, arguments: RequestMerge) -> str:
        async with context.sessions() as db:
            approval = await request_merge(
                db, context.clock, arguments.task, requested_by=context.agent_id
            )
        await record_action(
            context, "request_merge", {"task": arguments.task, "approval": approval.id}
        )
        return (
            f"Merge of task {arguments.task} requested as A{approval.id} ({approval.risk_class}). "
            "Nothing merges until the owner approves it with a passkey."
        )

    @refusing
    async def start_meeting(context: ToolContext, arguments: StartMeeting) -> str:
        meeting = await start_ceo_meeting(
            services.meetings(context),
            services.approvals(context),
            context.sessions,
            caller=context.agent_id,
            project=arguments.project,
            kind=arguments.kind,
        )
        await record_action(
            context,
            "start_meeting",
            {"meeting": meeting.id, "project": meeting.project_id, "kind": meeting.kind},
        )
        return f"Meeting {meeting.id} ({meeting.kind}) is starting for {arguments.project}."

    @refusing
    async def set_priority(context: ToolContext, arguments: SetPriority) -> str:
        async with context.sessions() as db:
            task = await db.get(Task, arguments.task)
            if task is None:
                raise WorkError(f"no task {arguments.task}")
            if task.status in CLOSED:
                raise WorkError(f"task {task.id} is {task.status}")
            before = task.priority
            task.priority = arguments.priority
            task.updated_at = context.clock.now()
            await db.commit()
        await record_action(
            context,
            "set_priority",
            {"task": task.id, "before": before, "after": arguments.priority},
        )
        return f"Task #{task.id} priority is now {arguments.priority} (was {before})."

    @refusing
    async def set_budget_tool(context: ToolContext, arguments: SetBudget) -> str:
        async with context.sessions() as db:
            answer = await set_budget(
                db,
                context.clock,
                services.ceo_settings(),
                caller=context.agent_id,
                scope=arguments.scope,
                target=str(arguments.id),
                micros=arguments.micros,
            )
            await db.commit()
        await record_action(
            context,
            "set_budget",
            {"scope": arguments.scope.value, "id": str(arguments.id), "micros": arguments.micros},
        )
        return answer

    def spec(
        name: str,
        description: str,
        model: type[BaseModel],
        handler: Any,
        *,
        read_only: bool = False,
    ) -> AgentToolSpec:
        return AgentToolSpec(
            name=name,
            description=description,
            input_model=model,
            roles=frozenset({CEO}),
            read_only=read_only,
            handler=handler,
        )

    return [
        spec(
            "discover_projects",
            "List candidate project folders (git repositories and plain folders) under the "
            "allowed roots, with running and saved CLI sessions, to take projects over.",
            DiscoverProjects,
            discover_projects,
            read_only=True,
        ),
        spec(
            "add_project",
            "Add an existing folder or repository on this server as a project. It gets a "
            "manager at once.",
            AddProject,
            add_project_tool,
        ),
        spec(
            "adopt_session",
            "Make a running CLI session (a pid from `discover_projects`) the project's "
            "manager. It continues once its current turn ends.",
            AdoptSession,
            adopt_session,
        ),
        spec(
            "assign_saved_session",
            "Make a saved, stopped CLI session the project's manager.",
            AssignSavedSession,
            assign_saved_session,
        ),
        spec(
            "staff_team",
            "Create a team (leads and workers) for a project manager now, within its size cap.",
            StaffTeam,
            staff_team,
        ),
        spec(
            "create_agent",
            "Add one lead or worker to a manager's team, within its size cap.",
            CreateAgent,
            create_agent,
        ),
        spec(
            "request_merge",
            "Ask the owner to merge a task's branch. Nothing merges until the owner approves "
            "it with a passkey.",
            RequestMerge,
            request_merge_tool,
        ),
        spec(
            "start_meeting",
            "Start a standup, planning or review meeting for a project.",
            StartMeeting,
            start_meeting,
        ),
        spec(
            "set_priority",
            "Set an open task's priority; a higher number runs first.",
            SetPriority,
            set_priority,
        ),
        spec(
            "set_budget",
            "Set an agent's, project's or department's budget in micro-USD, up to the owner's "
            "ceiling. Never your own.",
            SetBudget,
            set_budget_tool,
        ),
    ]
