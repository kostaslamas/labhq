"""Queue one owner message for the global CEO: the one path the web chat and the Call
Center share, so the scheduler, the budget and the backup retry treat them alike."""

from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.ceochat import conversation, message_reason
from labhq.clock import Clock
from labhq.db.enums import AgentStatus, WakeupSource
from labhq.db.models import WakeupRequest
from labhq.hierarchy import find_ceo
from labhq.scheduler import Outcome, Wakeup, enqueue

KEY_PREFIX = "owner-message:"


class Refusal(StrEnum):
    UNCONFIGURED = "ceo_unconfigured"
    INACTIVE = "ceo_inactive"
    BUSY = "ceo_busy"
    BUDGET_STOP = "ceo_budget_stop"


class CeoMessageError(RuntimeError):
    def __init__(self, refusal: Refusal, message: str) -> None:
        super().__init__(message)
        self.refusal = refusal


@dataclass(frozen=True)
class SentMessage:
    request: WakeupRequest
    # True when `key` had already queued this message: nothing new was sent.
    duplicate: bool


async def send_owner_message(
    db: AsyncSession, clock: Clock, text: str, *, key: str, refuse_busy: bool
) -> SentMessage:
    """Queue `text`, exactly as given, as an owner message to the CEO. Commits.

    `key` makes a retry send nothing twice. `refuse_busy` keeps the web chat's one turn at a
    time; other callers queue behind the CEO's current answer, since owner messages are
    never coalesced.
    """
    idempotency_key = f"{KEY_PREFIX}{key}"
    existing = await db.scalar(
        select(WakeupRequest).where(WakeupRequest.idempotency_key == idempotency_key)
    )
    if existing is not None:
        return SentMessage(existing, duplicate=True)
    ceo = await find_ceo(db)
    if ceo is None:
        raise CeoMessageError(Refusal.UNCONFIGURED, "Assign the CEO on the Projects page first.")
    if ceo.status is not AgentStatus.ACTIVE:
        raise CeoMessageError(Refusal.INACTIVE, "The CEO is not active.")
    earlier = await conversation(db, ceo.id)
    if refuse_busy and earlier and earlier[-1].status in {"queued", "running"}:
        raise CeoMessageError(
            Refusal.BUSY, "Wait for the CEO's current answer before sending again."
        )
    result = await enqueue(
        db,
        Wakeup(
            agent_id=ceo.id,
            source=WakeupSource.OWNER_MESSAGE,
            idempotency_key=idempotency_key,
            reason=message_reason(text, earlier),
        ),
        clock,
    )
    if result.outcome is Outcome.REFUSED:
        await db.rollback()
        raise CeoMessageError(Refusal.BUDGET_STOP, "The CEO's budget is exhausted.")
    await db.commit()
    return SentMessage(result.request, duplicate=False)
