"""The Sessions view of the last scan, and the actions on it.

Every action goes through the approval flow the CLI uses (`labhq.inventory`): this module
only finds the session in the last scan and reports what was requested. Nothing here reads a
transcript, and an action never runs by itself: continue, close, analyse and the folder
manager each record an approval the owner decides.
"""

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel, model_validator
from sqlalchemy import select

from labhq.adoption import AdoptionError, Adoptions
from labhq.api.deps import ClockDep, ContextDep, SessionDep
from labhq.api.errors import ApiError
from labhq.api.inventory.state import LAST
from labhq.approvals import ApprovalService
from labhq.auth.routes import SignedIn
from labhq.db.models import Project
from labhq.inventory import register  # noqa: F401  (registers the approval executors)
from labhq.inventory.analysis import Analyses, AnalysisError
from labhq.inventory.autoscan import pending_projects
from labhq.inventory.chooser import NoRunnerError
from labhq.inventory.close import SessionCloser
from labhq.inventory.continuing import continue_session
from labhq.inventory.folders import propose
from labhq.inventory.model import ProjectInventory, SessionInfo
from labhq.inventory.scope import real
from labhq.inventory.service import locate
from labhq.inventory.settings import get_inventory_settings

router = APIRouter(prefix="/inventory", tags=["inventory"])

REFUSED_CODE = "inventory_action_refused"
ERRORS = (AnalysisError, NoRunnerError, AdoptionError)


class GitOut(BaseModel):
    branch: str | None
    dirty_files: int
    last_commit_subject: str | None
    last_commit_at: datetime | None
    open_pr: str | None


class ProposalOut(BaseModel):
    # `continue`, `close` or `keep as history`.
    action: str
    reason: str


class SessionOut(BaseModel):
    tool: str
    session_id: str | None
    # `running`, `waiting for input` or `idle`.
    state: str
    idle_seconds: float | None
    last_activity: datetime | None
    pid: int | None
    # False for work labhq cannot continue itself (a Cursor IDE chat is handed off instead).
    resumable: bool
    proposal: ProposalOut


class ToolOut(BaseModel):
    tool: str
    logged_in: bool | None
    account: str | None
    plan: str | None
    plan_used_percent: float | None


class ScannedProject(BaseModel):
    root: str
    name: str
    has_repo: bool
    # The labhq project of the same folder, if it has been added.
    project_id: int | None
    git: GitOut
    sessions: list[SessionOut]


class FolderProposalOut(BaseModel):
    folder: str
    projects: list[str]


class SessionsOut(BaseModel):
    scanned_at: datetime | None
    left_out: int
    projects: list[ScannedProject]
    folders: list[FolderProposalOut]
    tools: list[ToolOut]


class ProjectIn(BaseModel):
    project: str


class SessionIn(BaseModel):
    project: str
    session_id: str | None = None
    pid: int | None = None

    @model_validator(mode="after")
    def names_one(self) -> "SessionIn":
        if self.session_id is None and self.pid is None:
            raise ValueError("name the session by session_id or pid")
        return self


class FolderIn(BaseModel):
    folder: str


class Requested(BaseModel):
    """What an action recorded: the approval to decide, or a hand-off task."""

    approval_id: int | None
    task_id: int | None = None
    # The estimate for an analysis, shown before anything runs; otherwise a one-line summary.
    summary: str


def _session_out(session: SessionInfo, project: ProjectInventory, index: int) -> SessionOut:
    proposal = project.proposals[index]
    return SessionOut(
        tool=session.tool,
        session_id=session.session_id,
        state=session.state.value,
        idle_seconds=session.idle_seconds,
        last_activity=session.last_activity,
        pid=session.pid,
        resumable=session.resumable,
        proposal=ProposalOut(action=proposal.action.value, reason=proposal.reason),
    )


@router.get("/sessions")
async def sessions_get(owner: SignedIn, db: SessionDep) -> SessionsOut:
    """The last scan's projects with their sessions; empty until a scan has run."""
    inventory = LAST.inventory
    if inventory is None:
        return SessionsOut(scanned_at=None, left_out=0, projects=[], folders=[], tools=[])
    added = {
        real(Path(path)): project_id
        for project_id, path in (await db.execute(select(Project.id, Project.repo_path))).all()
    }
    projects = [
        ScannedProject(
            root=str(p.root),
            name=p.name,
            has_repo=p.has_repo,
            project_id=added.get(real(p.root)),
            git=GitOut(
                branch=p.git.branch,
                dirty_files=p.git.dirty_files,
                last_commit_subject=p.git.last_commit_subject,
                last_commit_at=p.git.last_commit_at,
                open_pr=p.git.open_pr,
            ),
            sessions=[_session_out(s, p, i) for i, s in enumerate(p.sessions)],
        )
        for p in inventory.projects
    ]
    return SessionsOut(
        scanned_at=inventory.scanned_at,
        left_out=inventory.left_out,
        projects=projects,
        folders=[
            FolderProposalOut(folder=str(f.folder), projects=[str(p) for p in f.projects])
            for f in inventory.folders
        ],
        tools=[
            ToolOut(
                tool=t.tool,
                logged_in=t.logged_in,
                account=t.account,
                plan=t.plan,
                plan_used_percent=t.plan_used_percent,
            )
            for t in LAST.tools
        ],
    )


def _last_scan() -> None:
    if LAST.inventory is None:
        raise ApiError(409, "scan_first", "Scan first: there is no scan to act on yet.")


def _refused(error: Exception) -> ApiError:
    return ApiError(422, REFUSED_CODE, str(error))


@router.post("/actions/analyse", status_code=201)
async def action_analyse(
    body: ProjectIn, owner: SignedIn, context: ContextDep, clock: ClockDep
) -> Requested:
    """Estimate the analysis of one project and ask for the approval that starts it."""
    try:
        request = await Analyses(
            context.sessions, clock=clock, settings=get_inventory_settings()
        ).request(body.project)
    except ERRORS as error:
        raise _refused(error) from None
    return Requested(approval_id=request.approval_id, summary=request.text)


@router.post("/actions/close", status_code=201)
async def action_close(
    body: SessionIn, owner: SignedIn, context: ContextDep, clock: ClockDep
) -> Requested:
    """Ask to end an idle session's process (never mid-turn); the conversation stays saved."""
    _last_scan()
    assert LAST.inventory is not None
    try:
        _, session = locate(LAST.inventory, body.project, session_id=body.session_id, pid=body.pid)
        approval = await SessionCloser().request(
            ApprovalService(context.sessions, clock=clock), session
        )
    except ERRORS as error:
        raise _refused(error) from None
    return Requested(approval_id=approval.id, summary=f"Close {session.tool} {session.pid}.")


@router.post("/actions/continue", status_code=201)
async def action_continue(
    body: SessionIn, owner: SignedIn, context: ContextDep, clock: ClockDep
) -> Requested:
    """Adopt a running session, resume a saved one, or hand a Cursor IDE chat to a CLI agent."""
    _last_scan()
    assert LAST.inventory is not None
    try:
        chosen, session = locate(
            LAST.inventory, body.project, session_id=body.session_id, pid=body.pid
        )
        result = await continue_session(
            context.sessions,
            clock,
            Adoptions(context.sessions, clock=clock),
            session,
            project_name=chosen.name,
            data_dir=context.settings.data_dir,
        )
    except ERRORS as error:
        raise _refused(error) from None
    if result.approval is not None:
        return Requested(approval_id=result.approval.id, summary=f"Continue {session.tool}.")
    task = result.task
    assert task is not None
    return Requested(approval_id=None, task_id=task.id, summary=task.title)


@router.post("/actions/folder", status_code=201)
async def action_folder(
    body: FolderIn, owner: SignedIn, context: ContextDep, clock: ClockDep
) -> Requested:
    """Ask for the approval that creates a folder manager for a parent folder."""
    _last_scan()
    assert LAST.inventory is not None
    match = [
        f
        for f in LAST.inventory.folders
        if str(f.folder) == body.folder or f.folder.name == body.folder
    ]
    if len(match) != 1:
        raise _refused(ValueError(f"no single folder-manager proposal for {body.folder!r}"))
    approval = await propose(ApprovalService(context.sessions, clock=clock), match[0])
    return Requested(approval_id=approval.id, summary=f"Folder manager for {match[0].folder.name}.")


class NewProject(BaseModel):
    path: str
    name: str


@router.get("/new-projects")
async def new_projects(owner: SignedIn, db: SessionDep) -> list[NewProject]:
    """Projects the automatic scan announced that the owner has not yet added or skipped."""
    return [NewProject(path=p, name=Path(p).name) for p in await pending_projects(db)]
