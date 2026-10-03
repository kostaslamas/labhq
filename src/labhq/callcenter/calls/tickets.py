"""Calls and their requests: which call a question joins, and what its ticket says.

A call is a window of time (ADR 0004). A request joins the latest open call whose last
activity is inside the window; otherwise the stale calls close and a new one opens. The
request's id is the ticket the caller redeems. Nothing here commits: the caller owns the
transaction, so the request exists before any agent sees it.
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.callcenter.settings import CallCenterSettings, get_callcenter_settings
from labhq.clock import Clock
from labhq.db.enums import CallRequestStatus, CallStatus
from labhq.db.models import Call, CallRequest

TICKET_PREFIX = "call-"
TICKET_HEX_CHARS = 12


def new_ticket() -> str:
    # Short enough to read back; 48 random bits is plenty for tickets that expire in an hour.
    return f"{TICKET_PREFIX}{uuid.uuid4().hex[:TICKET_HEX_CHARS]}"


async def current_call(
    db: AsyncSession, clock: Clock, settings: CallCenterSettings | None = None
) -> tuple[Call, bool]:
    """The call a request made now belongs to, and whether it was opened for it."""
    settings = settings or get_callcenter_settings()
    now = clock.now()
    window_start = now - timedelta(seconds=settings.call_window_seconds)
    call = await db.scalar(
        select(Call)
        .where(Call.status == CallStatus.OPEN, Call.last_activity_at >= window_start)
        .order_by(Call.last_activity_at.desc(), Call.id.desc())
        .limit(1)
    )
    if call is not None:
        call.last_activity_at = now
        await db.flush()
        return call, False
    # Calls past the window are hung up: their sessions are never resumed again.
    await db.execute(
        update(Call)
        .where(Call.status == CallStatus.OPEN, Call.last_activity_at < window_start)
        .values(status=CallStatus.CLOSED, closed_at=now)
    )
    call = Call(opened_at=now, last_activity_at=now)
    db.add(call)
    await db.flush()
    return call, True


async def record_request(
    db: AsyncSession, clock: Clock, text: str, settings: CallCenterSettings | None = None
) -> CallRequest:
    """Store the owner's words, verbatim, in the current call."""
    call, _ = await current_call(db, clock, settings)
    request = CallRequest(
        call_id=call.id, request_id=new_ticket(), text=text, created_at=clock.now()
    )
    db.add(request)
    await db.flush()
    return request


def is_expired(request: CallRequest, now: datetime, settings: CallCenterSettings) -> bool:
    return now - request.created_at > timedelta(seconds=settings.ticket_expiry_seconds)


async def expire_if_old(
    db: AsyncSession, request: CallRequest, now: datetime, settings: CallCenterSettings
) -> bool:
    """Mark a pending request expired once it is past its time; return whether it is."""
    if not is_expired(request, now, settings):
        return False
    if request.status is CallRequestStatus.PENDING:
        request.status = CallRequestStatus.EXPIRED
        await db.flush()
    return True


async def next_pending(
    db: AsyncSession, clock: Clock, call_id: int, settings: CallCenterSettings
) -> CallRequest | None:
    """The oldest request of the call still waiting for the agent; old ones expire on the way."""
    while True:
        request = await db.scalar(
            select(CallRequest)
            .where(
                CallRequest.call_id == call_id,
                CallRequest.status == CallRequestStatus.PENDING,
            )
            .order_by(CallRequest.id)
            .limit(1)
        )
        if request is None or not await expire_if_old(db, request, clock.now(), settings):
            return request
