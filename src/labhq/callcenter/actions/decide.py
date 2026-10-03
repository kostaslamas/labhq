"""Approve or reject an approval by voice. Plan §5, rule 7: never a heavy approval."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.approvals import (
    ApprovalNotFoundError,
    ApprovalNotPendingError,
    ApprovalService,
    ConfirmationNotAllowedError,
)
from labhq.callcenter.answers.refs import approval_ref, parse_ref
from labhq.clock import Clock
from labhq.speech import join_sentences, speakable

DECIDER = "call_center"
CONFIRMATION = "voice"

# Spoken words, as a speech recogniser tends to deliver them, mapped to a verdict.
VERDICTS: dict[str, str] = {
    "approve": "approve",
    "approved": "approve",
    "yes": "approve",
    "reject": "reject",
    "rejected": "reject",
    "deny": "reject",
    "no": "reject",
}


def _parse_approval_id(reference: str) -> int | None:
    try:
        kind, number = parse_ref(reference)
    except ValueError:
        return None
    return number if kind == "approval" else None


async def decide(db: AsyncSession, clock: Clock, reference: str, verdict: str) -> str:
    approval_id = _parse_approval_id(reference)
    if approval_id is None:
        return speakable("I did not catch which approval. Say its reference, like A 12.")
    action = VERDICTS.get(verdict.strip().lower())
    if action is None:
        return speakable("Say approve or reject.")
    if db.bind is None:
        raise RuntimeError("decide needs a session bound to an engine")
    service = ApprovalService(async_sessionmaker(db.bind, expire_on_commit=False), clock=clock)
    ref = approval_ref(approval_id)
    try:
        if action == "approve":
            await service.approve(approval_id, decider=DECIDER, confirmation=CONFIRMATION)
        else:
            await service.reject(approval_id, decider=DECIDER, confirmation=CONFIRMATION)
    except ApprovalNotFoundError:
        return speakable(f"There is no approval {ref}.")
    except ApprovalNotPendingError:
        current = await service.get(approval_id)
        status = current.status.value.replace("_", " ")
        return speakable(f"Approval {ref} is already {status}.")
    except ConfirmationNotAllowedError:
        # The row stays pending and nothing ran; the confirmation registry, not this module,
        # decides what voice may approve.
        return speakable(
            join_sentences([f"Approval requested for {ref}", "Confirm it with your passkey"])
        )
    done = "approved" if action == "approve" else "rejected"
    return speakable(f"Approval {ref} {done}.")
