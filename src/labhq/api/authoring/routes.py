"""Add projects and agents from the web app, through the same services as the CLI.

Nothing here owns logic: `labhq.work` checks the directory and creates the rows, and the
`create_agent` approval of `labhq.hierarchy` is what activates a new agent (plan §5, rule 4),
decided on the approvals page like any other.
"""

import asyncio
from pathlib import Path

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from labhq import work
from labhq.adapters import default_registry
from labhq.adapters.kinds import UnknownAgentChoiceError, agent_choices, choice_named
from labhq.adapters.tmux import UnknownAgentKindError, default_kinds
from labhq.adoption.observe import AdoptionError, OwnerTmux
from labhq.adoption.request import Adoptions, works_on_project
from labhq.adoption.saved import list_saved_sessions
from labhq.adoption.settings import get_adoption_settings
from labhq.api.authoring.browser import router as browser_router
from labhq.api.authoring.schemas import (
    AddedAgent,
    AgentKindChoice,
    NewAgentBody,
    NewProjectBody,
    RegisteredProject,
    UpdateAgentBody,
    UpdatedAgent,
)
from labhq.api.deps import ClockDep, ContextDep, SessionDep
from labhq.api.errors import ApiError
from labhq.approvals import ApprovalService
from labhq.auth.routes import SignedIn
from labhq.db.enums import AgentStatus, RunStatus
from labhq.db.models import Agent, Project, Run
from labhq.hierarchy import CEO, CREATE_AGENT, MANAGER, Hierarchy, HierarchyError, check_reports_to
from labhq.hierarchy.roles import role
from labhq.usage.plan import agent_kind

router = APIRouter(tags=["authoring"])
router.include_router(browser_router)


class RunningManagerCandidate(BaseModel):
    pid: int
    kind: str
    cwd: str
    pane: str


class AdoptManagerBody(BaseModel):
    pid: int = Field(gt=0)


class AdoptManagerApproval(BaseModel):
    approval_id: int
    warnings: list[str]


class SavedSessionChoice(BaseModel):
    kind: str
    session_id: str
    updated_at: str


class AssignSavedSessionBody(BaseModel):
    kind: str
    session_id: str


@router.get("/projects/{project_id}/saved-sessions")
async def saved_sessions_list(
    project_id: int, kind: str, owner: SignedIn, db: SessionDep
) -> list[SavedSessionChoice]:
    """List exact sessions of the selected CLI in this project's directory."""
    try:
        project = await work.find_project(db, str(project_id))
        default_kinds.get(kind)
    except work.WorkError:
        raise ApiError(404, "project_not_found", f"There is no project {project_id}.") from None
    except UnknownAgentKindError:
        raise ApiError(422, "unknown_kind", f"There is no CLI agent kind {kind!r}.") from None
    found = await asyncio.to_thread(list_saved_sessions, kind, Path(project.repo_path))
    return [
        SavedSessionChoice(
            kind=item.kind, session_id=item.session_id, updated_at=item.updated_at.isoformat()
        )
        for item in found
    ]


@router.post("/projects/{project_id}/assign-saved-session", status_code=202)
async def assign_saved_session(
    project_id: int,
    body: AssignSavedSessionBody,
    owner: SignedIn,
    context: ContextDep,
    db: SessionDep,
) -> AdoptManagerApproval:
    try:
        project = await work.find_project(db, str(project_id))
        default_kinds.get(body.kind)
    except work.WorkError:
        raise ApiError(404, "project_not_found", f"There is no project {project_id}.") from None
    except UnknownAgentKindError:
        raise ApiError(422, "unknown_kind", f"There is no CLI agent kind {body.kind!r}.") from None
    if choice_named(body.kind).found() is None:
        raise ApiError(422, "kind_unavailable", f"{body.kind} is not installed on this server.")
    try:
        approval = await Adoptions(context.sessions, clock=context.clock).request_saved(
            kind=body.kind, session_id=body.session_id, project=project
        )
    except LookupError as error:
        raise ApiError(422, "session_not_found", str(error)) from None
    except AdoptionError as error:
        raise ApiError(409, "agent_running", str(error)) from None
    except HierarchyError as error:
        raise ApiError(409, "manager_exists", str(error)) from None
    return AdoptManagerApproval(
        approval_id=approval.id, warnings=list(approval.payload.get("warnings", []))
    )


@router.get("/projects/{project_id}/running-managers")
async def running_managers_list(
    project_id: int, owner: SignedIn, context: ContextDep, db: SessionDep
) -> list[RunningManagerCandidate]:
    """Show CLI agents in the owner's tmux that can be adopted for this project."""
    try:
        project = await work.find_project(db, str(project_id))
    except work.WorkError:
        raise ApiError(404, "project_not_found", f"There is no project {project_id}.") from None
    tmux = OwnerTmux(get_adoption_settings().owner_tmux_socket)
    found = await Adoptions(context.sessions, clock=context.clock).discover()
    candidates = []
    for agent in found:
        if not works_on_project(agent.cwd, Path(project.repo_path)):
            continue
        pane = await asyncio.to_thread(tmux.pane_of, agent.pid)
        if pane is not None:
            candidates.append(
                RunningManagerCandidate(
                    pid=agent.pid, kind=agent.kind, cwd=str(agent.cwd), pane=pane
                )
            )
    return candidates


@router.post("/projects/{project_id}/adopt-manager", status_code=202)
async def adopt_manager_request(
    project_id: int,
    body: AdoptManagerBody,
    owner: SignedIn,
    context: ContextDep,
    db: SessionDep,
) -> AdoptManagerApproval:
    """Ask approval before moving an owner's running tmux agent into labhq."""
    try:
        project = await work.find_project(db, str(project_id))
    except work.WorkError:
        raise ApiError(404, "project_not_found", f"There is no project {project_id}.") from None
    adoption = Adoptions(context.sessions, clock=context.clock)
    try:
        request = await adoption.request(body.pid, project=project.name, require_tmux=True)
    except AdoptionError as error:
        raise ApiError(422, "adoption_not_valid", str(error)) from None
    except HierarchyError as error:
        raise ApiError(409, "manager_exists", str(error)) from None
    return AdoptManagerApproval(approval_id=request.approval.id, warnings=list(request.warnings))


@router.get("/agent-kinds")
async def agent_kinds_list() -> list[AgentKindChoice]:
    """Every agent a person can add, with whether its program is installed on this machine."""
    return [
        AgentKindChoice(
            name=choice.name,
            display_name=choice.display_name,
            adapter=choice.adapter,
            binary=choice.binary,
            available=choice.found() is not None,
        )
        for choice in agent_choices()
    ]


@router.post("/projects", status_code=201)
async def projects_create(
    body: NewProjectBody, owner: SignedIn, db: SessionDep, clock: ClockDep
) -> RegisteredProject:
    """Register an existing directory on this machine as a project."""
    path = Path(body.repo_path)
    if not path.is_absolute():
        raise ApiError(422, "repo_path_not_absolute", "Give the project's full path.")
    try:
        repo = work.check_project_directory(path)
    except work.WorkError as error:
        raise ApiError(422, "not_a_directory", str(error)) from None
    try:
        project = await work.add_project(
            db, clock, name=body.name, repo=repo, budget=body.budget_micros
        )
    except work.WorkError as error:
        raise ApiError(409, "project_exists", str(error)) from None
    await db.commit()
    return RegisteredProject(
        id=project.id,
        name=project.name,
        repo_path=project.repo_path,
        budget_micros=project.budget_micros,
    )


@router.post("/projects/{project_id}/agents", status_code=201)
async def project_agents_create(
    project_id: int,
    body: NewAgentBody,
    owner: SignedIn,
    context: ContextDep,
    db: SessionDep,
    clock: ClockDep,
) -> AddedAgent:
    """Add an agent to a project. It starts pending: nothing runs until its approval."""
    try:
        project = await work.find_project(db, str(project_id))
    except work.WorkError:
        raise ApiError(404, "project_not_found", f"There is no project {project_id}.") from None
    try:
        role(body.role)
        if body.role == CEO:
            raise HierarchyError("the CEO belongs to no project")
        reports_to = body.reports_to
        if body.role == MANAGER:
            ceo = await Hierarchy(
                context.sessions, clock=context.clock, adapters=default_registry.adapter_keys()
            ).ensure_ceo()
            if reports_to is not None and reports_to != ceo.id:
                raise HierarchyError("a project manager reports to the global CEO")
            reports_to = ceo.id
        elif reports_to is not None:
            manager = await work.find_agent(db, reports_to)
            if manager.project_id != project.id:
                raise work.WorkError(f"agent {manager.id} is not on this project")
            check_reports_to(body.role, manager.role)
        agent = await work.add_agent(
            db,
            clock,
            adapters=default_registry.adapter_keys(),
            project=str(project.id),
            role=body.role,
            title=body.title,
            kind=body.kind,
            reports_to=reports_to,
            budget=body.budget_micros,
        )
    except UnknownAgentChoiceError as error:
        raise ApiError(422, "unknown_kind", str(error)) from None
    except HierarchyError as error:
        raise ApiError(422, "reporting_line", str(error)) from None
    except work.WorkError as error:
        raise ApiError(422, "agent_not_valid", str(error)) from None
    await db.commit()
    service = ApprovalService(context.sessions, clock=context.clock)
    approval = await service.request(
        CREATE_AGENT, {"agent_id": agent.id}, agent_id=agent.reports_to
    )
    return AddedAgent(
        id=agent.id,
        project_id=project.id,
        role=agent.role,
        title=agent.title,
        adapter=agent.adapter,
        kind=body.kind,
        reports_to=agent.reports_to,
        budget_micros=agent.budget_micros,
        status=agent.status,
        approval_id=approval.id,
    )


@router.patch("/projects/{project_id}/agents/{agent_id}")
async def project_agent_update(
    project_id: int,
    agent_id: int,
    body: UpdateAgentBody,
    owner: SignedIn,
    db: SessionDep,
    clock: ClockDep,
) -> UpdatedAgent:
    """Edit an existing assignment without creating another agent or manager."""
    agent = await db.get(Agent, agent_id)
    if agent is None or agent.project_id != project_id or agent.status == AgentStatus.RETIRED:
        raise ApiError(404, "agent_not_found", "This project has no such active agent.")
    title = body.title.strip()
    if not title:
        raise ApiError(422, "agent_not_valid", "Give the agent a title.")
    try:
        choice = choice_named(body.kind)
    except UnknownAgentChoiceError as error:
        raise ApiError(422, "unknown_kind", str(error)) from None
    old_kind = agent_kind(agent.adapter, agent.config)
    if body.kind != old_kind:
        if isinstance(agent.config.get("adoption"), dict):
            raise ApiError(
                409,
                "adopted_agent",
                "This agent owns a continued session; change its session first.",
            )
        busy = await db.scalar(
            select(Run.id)
            .where(Run.agent_id == agent.id, Run.status.in_((RunStatus.QUEUED, RunStatus.RUNNING)))
            .limit(1)
        )
        if busy is not None:
            raise ApiError(409, "agent_busy", "Wait for the agent's current run to finish.")
        if choice.found() is None:
            raise ApiError(422, "kind_unavailable", f"{body.kind} is not installed on this server.")
    if agent.role == MANAGER:
        if body.reports_to != agent.reports_to:
            raise ApiError(422, "reporting_line", "A manager reports to the global CEO.")
    elif body.reports_to is not None:
        parent = await db.get(Agent, body.reports_to)
        if (
            parent is None
            or parent.project_id != project_id
            or parent.status == AgentStatus.RETIRED
            or parent.id == agent.id
        ):
            raise ApiError(422, "reporting_line", "Choose an active agent on this project.")
        try:
            check_reports_to(agent.role, parent.role)
        except HierarchyError as error:
            raise ApiError(422, "reporting_line", str(error)) from None
    if body.kind != old_kind:
        config = {key: value for key, value in agent.config.items() if key != "agent"}
        agent.config = {**config, **choice.config}
        agent.adapter = choice.adapter
    agent.title = title
    agent.reports_to = body.reports_to
    agent.budget_micros = body.budget_micros
    agent.updated_at = clock.now()
    await db.commit()
    return UpdatedAgent(
        id=agent.id,
        title=agent.title,
        kind=body.kind,
        reports_to=agent.reports_to,
        budget_micros=agent.budget_micros,
    )


@router.delete("/projects/{project_id}", status_code=204)
async def project_delete(project_id: int, owner: SignedIn, db: SessionDep) -> Response:
    """Remove a project with its agents, tasks, meetings and costs; the folder is not touched."""
    project = await db.get(Project, project_id)
    if project is None:
        raise ApiError(404, "project_not_found", f"There is no project {project_id}.")
    busy = await db.scalar(
        select(Run.id)
        .join(Agent, Agent.id == Run.agent_id)
        .where(
            Agent.project_id == project_id,
            Run.status.in_((RunStatus.QUEUED, RunStatus.RUNNING)),
        )
        .limit(1)
    )
    if busy is not None:
        raise ApiError(409, "project_busy", "Wait for the project's current runs to finish.")
    await db.delete(project)
    await db.commit()
    return Response(status_code=204)
