"""Add projects and agents from the web app, through the same services as the CLI.

Nothing here owns logic: `labhq.work` checks the directory and creates the rows, and the
`create_agent` approval of `labhq.hierarchy` is what activates a new agent (plan §5, rule 4),
decided on the approvals page like any other.
"""

from pathlib import Path

from fastapi import APIRouter

from labhq import work
from labhq.adapters import default_registry
from labhq.adapters.kinds import UnknownAgentChoiceError, agent_choices
from labhq.api.authoring.browser import router as browser_router
from labhq.api.authoring.schemas import (
    AddedAgent,
    AgentKindChoice,
    NewAgentBody,
    NewProjectBody,
    RegisteredProject,
)
from labhq.api.deps import ClockDep, ContextDep, SessionDep
from labhq.api.errors import ApiError
from labhq.approvals import ApprovalService
from labhq.auth.routes import SignedIn
from labhq.hierarchy import CEO, CREATE_AGENT, HierarchyError, check_reports_to
from labhq.hierarchy.roles import role

router = APIRouter(tags=["authoring"])
router.include_router(browser_router)


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
        if body.reports_to is not None:
            manager = await work.find_agent(db, body.reports_to)
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
            reports_to=body.reports_to,
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
