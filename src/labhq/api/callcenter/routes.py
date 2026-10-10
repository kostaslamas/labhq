"""Decision rooms over HTTP: list them, start one, speak in it, close it, read what it decided.

The transcript itself is `/api/meetings/{id}`, so a room reads like any meeting. These routes
add what only a live room has. Starting is the existing `start_meeting` approval, a tap; the
cost range and hard cap it shows were fixed when the CEO proposed the room. Nothing decided in
a room runs without the owner approving its action items (`labhq.meetings.actions`).
"""

import contextlib
from typing import Annotated

from fastapi import APIRouter, Header, Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.adapters.kinds import TMUX_ADAPTER
from labhq.adoption.state import state_of
from labhq.api.callcenter.schemas import (
    Decided,
    DecidedAction,
    RoomItem,
    RoomMessage,
    Waiting,
)
from labhq.api.deps import ClockDep, ContextDep, OwnerDep, SessionDep
from labhq.api.errors import ApiError
from labhq.api.meetings.schemas import Message
from labhq.approvals import ApprovalService
from labhq.ceoorg.background import spawn
from labhq.ceoorg.meetings import meeting_service
from labhq.clock import Clock
from labhq.db.enums import ApprovalStatus, MeetingStatus
from labhq.db.models import (
    Agent,
    Approval,
    Meeting,
    MeetingActionItem,
    MeetingDecision,
    MeetingParticipant,
    Project,
)
from labhq.meetings import (
    MeetingClosedError,
    RoomClosedError,
    add_owner_entry,
    default_kinds,
    get_meeting_settings,
)
from labhq.meetings.figures import room_figures

router = APIRouter(prefix="/callcenter", tags=["callcenter"])

RoomId = Annotated[int, Path(ge=1)]
IdempotencyKey = Annotated[
    str | None,
    Header(max_length=128, description="One per user intent; a retry reuses it."),
]
LIST_LIMIT = 20
TAP = "tap"


def _tmux(agent: Agent) -> bool:
    return agent.adapter == TMUX_ADAPTER or state_of(agent) is not None


async def _item(db: AsyncSession, clock: Clock, meeting: Meeting, project_name: str) -> RoomItem:
    settings = get_meeting_settings()
    figures = await room_figures(db, clock, meeting, settings)
    approval = await db.get(Approval, meeting.approval_id) if meeting.approval_id else None
    waiting = None
    if meeting.waiting_agent_id is not None and meeting.waiting_reason:
        agent = await db.get_one(Agent, meeting.waiting_agent_id)
        waiting = Waiting(
            agent_id=agent.id,
            agent_name=agent.title,
            reason=meeting.waiting_reason,
            can_interrupt=_tmux(agent),
        )
    return RoomItem(
        id=meeting.id,
        status=meeting.status,
        project_id=meeting.project_id,
        project_name=project_name,
        agenda=meeting.agenda,
        pinned_kind=meeting.pinned_kind,
        pinned_id=meeting.pinned_id,
        estimate_micros=figures.low_micros,
        estimate_high_micros=figures.high_micros,
        estimate_source=figures.source,
        cost_cap_micros=figures.cap_micros,
        cost_micros=figures.spent_micros,
        equivalent_cost=figures.equivalent_cost,
        plan_used_percent=figures.plan_used_percent,
        over_estimate=meeting.over_estimate_at is not None,
        approval_id=meeting.approval_id,
        approval_status=approval.status if approval else None,
        turns_used=figures.turns,
        turn_cap=figures.turn_cap,
        waiting=waiting,
        end_reason=meeting.end_reason,
        created_at=meeting.created_at,
        ended_at=meeting.ended_at,
    )


def _live_kinds() -> list[str]:
    return [key for key in default_kinds if default_kinds.get(key).live]


async def _room(db: AsyncSession, room_id: int) -> Meeting:
    meeting = await db.get(Meeting, room_id)
    if meeting is None or meeting.kind not in _live_kinds():
        raise ApiError(404, "room_not_found", f"There is no decision room {room_id}.")
    return meeting


@router.get("/rooms")
async def rooms_list(owner: OwnerDep, db: SessionDep, clock: ClockDep) -> list[RoomItem]:
    """The newest rooms, newest first; the widget opens the first that is not over."""
    rows = (
        await db.execute(
            select(Meeting, Project.name)
            .join(Project, Meeting.project_id == Project.id)
            .where(Meeting.kind.in_(_live_kinds()))
            .order_by(Meeting.id.desc())
            .limit(LIST_LIMIT)
        )
    ).all()
    return [await _item(db, clock, meeting, name) for meeting, name in rows]


@router.post("/rooms/{room_id}/start", status_code=202)
async def room_start(
    room_id: RoomId, owner: OwnerDep, context: ContextDep, db: SessionDep
) -> RoomItem:
    clock = context.clock
    """The owner's tap on the room's start approval, then the room opens in the background."""
    meeting = await _room(db, room_id)
    if meeting.status is not MeetingStatus.REQUESTED or meeting.approval_id is None:
        raise ApiError(409, "room_not_waiting", "This room is not waiting for approval.")
    approvals = ApprovalService(context.sessions, clock=context.clock)
    approval = await db.get_one(Approval, meeting.approval_id)
    if approval.status is ApprovalStatus.PENDING:
        await approvals.approve(approval.id, decider=f"web:{owner.subject}", confirmation=TAP)
    elif approval.status not in {ApprovalStatus.APPROVED, ApprovalStatus.EXECUTED}:
        raise ApiError(409, "room_not_approved", "The start of this room was refused.")
    service = meeting_service(context.sessions, context.clock, approvals)
    spawn(service.start(room_id), name=f"room-{room_id}")
    db.expire_all()
    return await _item(db, clock, await _room(db, room_id), await _project_name(db, meeting))


@router.post("/rooms/{room_id}/decline")
async def room_decline(
    room_id: RoomId, owner: OwnerDep, context: ContextDep, db: SessionDep
) -> RoomItem:
    clock = context.clock
    """Refuse the start; the room is cancelled and nobody is asked."""
    meeting = await _room(db, room_id)
    if meeting.status is not MeetingStatus.REQUESTED or meeting.approval_id is None:
        raise ApiError(409, "room_not_waiting", "This room is not waiting for approval.")
    approvals = ApprovalService(context.sessions, clock=context.clock)
    await approvals.reject(meeting.approval_id, decider=f"web:{owner.subject}", confirmation=TAP)
    await meeting_service(context.sessions, context.clock, approvals).start(room_id)
    db.expire_all()
    return await _item(db, clock, await _room(db, room_id), await _project_name(db, meeting))


async def _project_name(db: AsyncSession, meeting: Meeting) -> str:
    return (await db.get_one(Project, meeting.project_id)).name


@router.post("/rooms/{room_id}/messages", status_code=201)
async def room_say(
    room_id: RoomId,
    body: RoomMessage,
    owner: OwnerDep,
    context: ContextDep,
    db: SessionDep,
    clock: ClockDep,
    idempotency_key: IdempotencyKey = None,
) -> Message:
    """Say something as the owner. It is recorded at once; the agents answer in the background."""
    meeting = await _room(db, room_id)
    try:
        entry = await add_owner_entry(
            context.sessions,
            clock,
            meeting_id=room_id,
            text=body.text,
            external_ref=f"web:{idempotency_key}" if idempotency_key else None,
        )
    except MeetingClosedError:
        raise ApiError(
            409, "room_closed", "This room is over; it takes no more messages."
        ) from None
    if entry is None:
        raise ApiError(409, "duplicate_message", "That message was already recorded.")
    if meeting.status is MeetingStatus.RUNNING:
        service = meeting_service(
            context.sessions, clock, ApprovalService(context.sessions, clock=clock)
        )
        spawn(service.room.advance(room_id), name=f"room-{room_id}-advance")
    participant = await db.get_one(MeetingParticipant, entry.participant_id)
    return Message(
        id=entry.id,
        source=entry.source,
        speaker=participant.display_name,
        agent_id=None,
        text=entry.text,
        created_at=entry.created_at,
    )


@router.post("/rooms/{room_id}/close", status_code=202)
async def room_close(room_id: RoomId, owner: OwnerDep, context: ContextDep, db: SessionDep) -> None:
    """Write the minutes and end the room, in the background."""
    meeting = await _room(db, room_id)
    if meeting.status is not MeetingStatus.RUNNING:
        raise ApiError(409, "room_not_running", "This room is not running.")
    service = meeting_service(
        context.sessions, context.clock, ApprovalService(context.sessions, clock=context.clock)
    )

    async def close() -> None:
        # Closed by the CEO or the cap meanwhile: nothing left to do.
        with contextlib.suppress(RoomClosedError):
            await service.room.close(room_id)

    spawn(close(), name=f"room-{room_id}-close")


@router.get("/decisions")
async def decisions_list(owner: OwnerDep, db: SessionDep) -> list[Decided]:
    """What each ended room decided about the proposal it was pinned to, for the cards."""
    meetings = list(
        await db.scalars(
            select(Meeting)
            .where(
                Meeting.kind.in_(_live_kinds()),
                Meeting.status == MeetingStatus.ENDED,
                Meeting.pinned_kind.is_not(None),
                Meeting.pinned_id.is_not(None),
            )
            .order_by(Meeting.id.desc())
            .limit(100)
        )
    )
    decided = []
    for meeting in meetings:
        texts = list(
            await db.scalars(
                select(MeetingDecision.text)
                .where(MeetingDecision.meeting_id == meeting.id)
                .order_by(MeetingDecision.position)
            )
        )
        if not texts or meeting.pinned_kind is None or meeting.pinned_id is None:
            continue
        items = await db.execute(
            select(MeetingActionItem.text, Approval.id, Approval.status)
            .outerjoin(Approval, MeetingActionItem.approval_id == Approval.id)
            .where(MeetingActionItem.meeting_id == meeting.id)
            .order_by(MeetingActionItem.id)
        )
        decided.append(
            Decided(
                meeting_id=meeting.id,
                pinned_kind=meeting.pinned_kind,
                pinned_id=meeting.pinned_id,
                decisions=texts,
                actions=[
                    DecidedAction(text=text, approval_id=approval_id, approval_status=status)
                    for text, approval_id, status in items
                ],
                ended_at=meeting.ended_at or meeting.created_at,
            )
        )
    return decided
