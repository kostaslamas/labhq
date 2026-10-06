"""Configure the one CEO and carry the owner's direct conversation with it."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter
from pydantic import BaseModel, Field, StringConstraints

from labhq.adapters import default_registry
from labhq.adapters.kinds import UnknownAgentChoiceError
from labhq.api.deps import ContextDep, SessionDep
from labhq.api.errors import ApiError
from labhq.auth.routes import SignedIn
from labhq.ceochat import conversation
from labhq.ceochat_send import CeoMessageError, send_owner_message
from labhq.ceoreports import recent_reports
from labhq.db.enums import TaskStatus
from labhq.db.models import Task
from labhq.hierarchy import Hierarchy, HierarchyError
from labhq.usage.plan import agent_kind, fallback_kind
from labhq.work import WorkError
from labhq.work.progress import owner_decide

router = APIRouter(tags=["org"])


class CeoAssignment(BaseModel):
    id: int | None
    primary_kind: str | None
    backup_kind: str | None


class SetCeoAssignment(BaseModel):
    primary_kind: str = Field(min_length=1)
    backup_kind: str | None = None


class CeoChatTurn(BaseModel):
    id: int
    text: str
    reply: str | None
    status: Literal["queued", "running", "answered", "failed"]
    created_at: datetime


class SendCeoMessage(BaseModel):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class CeoReportOut(BaseModel):
    id: int
    text: str
    refs: list[str]
    task_id: int | None
    task_title: str | None
    awaiting_decision: bool
    created_at: datetime


class OwnerDecisionBody(BaseModel):
    # Optional when accepting; returning has to say what still needs work.
    feedback: Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)] = ""


class OwnerDecisionOut(BaseModel):
    task_id: int
    status: TaskStatus


def hierarchy(context: ContextDep) -> Hierarchy:
    return Hierarchy(
        context.sessions,
        clock=context.clock,
        adapters=default_registry.adapter_keys(),
    )


@router.get("/org/ceo")
async def ceo_get(owner: SignedIn, context: ContextDep) -> CeoAssignment:
    """The global CEO assignment, or empty fields before it has been configured."""
    ceo = await hierarchy(context).current_ceo()
    if ceo is None:
        return CeoAssignment(id=None, primary_kind=None, backup_kind=None)
    return CeoAssignment(
        id=ceo.id,
        primary_kind=agent_kind(ceo.adapter, ceo.config),
        backup_kind=fallback_kind(ceo.config),
    )


@router.put("/org/ceo")
async def ceo_put(body: SetCeoAssignment, owner: SignedIn, context: ContextDep) -> CeoAssignment:
    """Configure one CEO for all projects without replacing its identity or team."""
    try:
        ceo = await hierarchy(context).configure_ceo(body.primary_kind, body.backup_kind)
    except (HierarchyError, UnknownAgentChoiceError) as error:
        raise ApiError(422, "ceo_assignment_invalid", str(error)) from None
    return CeoAssignment(
        id=ceo.id,
        primary_kind=agent_kind(ceo.adapter, ceo.config),
        backup_kind=fallback_kind(ceo.config),
    )


@router.get("/org/ceo/messages")
async def ceo_messages_get(
    owner: SignedIn, context: ContextDep, db: SessionDep
) -> list[CeoChatTurn]:
    """Recent direct messages, including queued and failed turns."""
    ceo = await hierarchy(context).current_ceo()
    if ceo is None:
        return []
    return [
        CeoChatTurn.model_validate(turn, from_attributes=True)
        for turn in await conversation(db, ceo.id)
    ]


@router.post("/org/ceo/messages", status_code=202)
async def ceo_messages_post(
    body: SendCeoMessage, owner: SignedIn, context: ContextDep, db: SessionDep
) -> CeoChatTurn:
    """Queue one owner turn through the CEO's normal scheduler, budget and backup path."""
    try:
        sent = await send_owner_message(
            db, context.clock, body.text, key=uuid4().hex, refuse_busy=True
        )
    except CeoMessageError as error:
        raise ApiError(409, error.refusal.value, str(error)) from None
    return CeoChatTurn(
        id=sent.request.id,
        text=body.text,
        reply=None,
        status="queued",
        created_at=sent.request.created_at,
    )


@router.get("/org/ceo/reports")
async def ceo_reports_get(owner: SignedIn, db: SessionDep) -> list[CeoReportOut]:
    """The CEO's recent reports to the owner, oldest first."""
    return [
        CeoReportOut.model_validate(report, from_attributes=True)
        for report in await recent_reports(db)
    ]


async def _decide(
    db: SessionDep, context: ContextDep, task_id: int, *, accept: bool, feedback: str
) -> OwnerDecisionOut:
    task = await db.get(Task, task_id)
    if task is None:
        raise ApiError(404, "task_not_found", f"There is no task {task_id}.")
    try:
        await owner_decide(db, context.clock, task, accept=accept, feedback=feedback)
    except WorkError as error:
        await db.rollback()
        raise ApiError(409, "task_not_awaiting_owner", str(error)) from None
    await db.commit()
    return OwnerDecisionOut(task_id=task.id, status=task.status)


@router.post("/org/tasks/{task_id}/accept")
async def task_accept(
    task_id: int, body: OwnerDecisionBody, owner: SignedIn, context: ContextDep, db: SessionDep
) -> OwnerDecisionOut:
    """The owner closes a root objective the CEO reported as done."""
    return await _decide(
        db, context, task_id, accept=True, feedback=body.feedback or "Accepted by the owner."
    )


@router.post("/org/tasks/{task_id}/return")
async def task_return(
    task_id: int, body: OwnerDecisionBody, owner: SignedIn, context: ContextDep, db: SessionDep
) -> OwnerDecisionOut:
    """The owner sends a root objective back to its manager with what still needs work."""
    if not body.feedback:
        raise ApiError(422, "feedback_required", "Say what still needs work.")
    return await _decide(db, context, task_id, accept=False, feedback=body.feedback)
