"""Configure the one CEO and carry the owner's direct conversation with it."""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import uuid4

from fastapi import APIRouter
from pydantic import BaseModel, Field, StringConstraints

from labhq.adapters import default_registry
from labhq.adapters.kinds import UnknownAgentChoiceError
from labhq.api.deps import ContextDep, SessionDep
from labhq.api.errors import ApiError
from labhq.auth.routes import SignedIn
from labhq.ceochat import ConversationTurn, conversation
from labhq.ceochat_actions import split_actions
from labhq.ceochat_send import CeoMessageError, send_owner_message
from labhq.ceoreports import recent_reports
from labhq.db.enums import TaskStatus
from labhq.db.models import Task
from labhq.hierarchy import Hierarchy, HierarchyError
from labhq.meetings.proposal import default_proposals
from labhq.usage.plan import agent_kind, fallback_kind
from labhq.work import WorkError
from labhq.work.progress import owner_decide

SUMMARY_CHARS = 400

router = APIRouter(tags=["org"])


class CeoAssignment(BaseModel):
    id: int | None
    primary_kind: str | None
    backup_kind: str | None


class SetCeoAssignment(BaseModel):
    primary_kind: str = Field(min_length=1)
    backup_kind: str | None = None


class PinnedProposal(BaseModel):
    kind: Literal["report", "approval"]
    id: int = Field(ge=1)
    # What the owner can do with it from the widget; the server does not act on these.
    options: list[Literal["approve", "reject", "show"]] = Field(default_factory=list, max_length=3)


class CeoContext(BaseModel):
    """Where the owner was and what they pinned, sent as data and never typed (issue #199)."""

    route: Annotated[str, StringConstraints(max_length=200)] | None = None
    project_id: int | None = None
    pinned: PinnedProposal | None = None


class ChatAction(BaseModel):
    verb: Literal["approve", "reject", "show"]
    target_kind: str
    target_id: int


class CeoChatTurn(BaseModel):
    id: int
    text: str
    reply: str | None
    status: Literal["queued", "running", "answered", "failed"]
    created_at: datetime
    context: CeoContext | None = None
    # Buttons the CEO ended its reply with; `reply` no longer holds their markers.
    actions: list[ChatAction] = Field(default_factory=list)


class SendCeoMessage(BaseModel):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    context: CeoContext | None = None


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


def _turn_out(turn: ConversationTurn) -> CeoChatTurn:
    reply, actions = split_actions(turn.reply) if turn.reply else (None, [])
    context = turn.context or {}
    pinned = context.get("pinned")
    return CeoChatTurn(
        id=turn.id,
        text=turn.text,
        reply=reply,
        status=turn.status,
        created_at=turn.created_at,
        context=CeoContext(
            route=context.get("route"),
            project_id=context.get("project_id"),
            pinned=PinnedProposal.model_validate(pinned) if isinstance(pinned, dict) else None,
        )
        if turn.context
        else None,
        actions=[ChatAction.model_validate(action, from_attributes=True) for action in actions],
    )


async def _stored_context(db: SessionDep, context: CeoContext | None) -> dict[str, Any] | None:
    """The context as stored with the message: the proposal is read here, not taken on trust."""
    if context is None:
        return None
    stored: dict[str, Any] = {"route": context.route, "project_id": context.project_id}
    if context.pinned is not None:
        described = await default_proposals.get(context.pinned.kind)(db, context.pinned.id)
        if described is None:
            raise ApiError(
                404, "proposal_not_found", f"There is no {context.pinned.kind} {context.pinned.id}."
            )
        stored["project_id"] = described.project_id or context.project_id
        stored["pinned"] = {
            "kind": described.kind,
            "id": described.id,
            "project_id": described.project_id,
            "options": context.pinned.options,
            "summary": described.text[:SUMMARY_CHARS],
        }
    return {key: value for key, value in stored.items() if value is not None}


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
    return [_turn_out(turn) for turn in await conversation(db, ceo.id)]


@router.post("/org/ceo/messages", status_code=202)
async def ceo_messages_post(
    body: SendCeoMessage, owner: SignedIn, context: ContextDep, db: SessionDep
) -> CeoChatTurn:
    """Queue one owner turn through the CEO's normal scheduler, budget and backup path."""
    stored = await _stored_context(db, body.context)
    try:
        sent = await send_owner_message(
            db, context.clock, body.text, key=uuid4().hex, refuse_busy=True, context=stored
        )
    except CeoMessageError as error:
        raise ApiError(409, error.refusal.value, str(error)) from None
    return CeoChatTurn(
        id=sent.request.id,
        text=body.text,
        reply=None,
        status="queued",
        created_at=sent.request.created_at,
        context=body.context,
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
