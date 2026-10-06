"""Send the owner's words to the global CEO, or a clearer wording once the owner confirms it.

The owner's rule: orders go to the CEO, who delegates down; the Call Center creates no task
and talks to no manager. What reaches the CEO is the stored text of a request of this call,
by its id, or a proposal the owner confirmed in a later request of the same call. Nothing
is added: no preamble, no role, no context. Every refusal is a `BoundError` the agent reads.
"""

import re

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.callcenter.calls.bounds import BoundError, stored_request
from labhq.ceochat_send import KEY_PREFIX, CeoMessageError, send_owner_message
from labhq.clock import Clock
from labhq.db.enums import ProposalStatus
from labhq.db.models import CallRequest, WakeupRequest, WordingProposal
from labhq.speech import speakable

SENT = "Sent to the CEO."
ALREADY_SENT = "That was already sent to the CEO."
MAX_CHARS = 4000

# The owner's stored words decide a proposal; a no anywhere outweighs a yes.
_REJECT = re.compile(r"\b(no|nope|don'?t|do not|not|never|cancel|wrong|stop|wait)\b", re.IGNORECASE)
_CONFIRM = re.compile(
    r"\b(yes|yeah|yep|confirm(ed)?|correct|right|ok(ay)?|sure|send it|go ahead)\b",
    re.IGNORECASE,
)


def request_key(request_id: str) -> str:
    return f"call-request:{request_id}"


def proposal_key(proposal_id: int) -> str:
    return f"call-proposal:{proposal_id}"


async def _queued(db: AsyncSession, key: str) -> bool:
    query = exists().where(WakeupRequest.idempotency_key == f"{KEY_PREFIX}{key}")
    return bool(await db.scalar(select(query)))


async def _sent_proposal(db: AsyncSession, request_id: str) -> WordingProposal | None:
    return await db.scalar(
        select(WordingProposal).where(
            WordingProposal.request_id == request_id,
            WordingProposal.status == ProposalStatus.SENT,
        )
    )


async def _send(db: AsyncSession, clock: Clock, text: str, key: str) -> str:
    try:
        sent = await send_owner_message(db, clock, text, key=key, refuse_busy=False)
    except CeoMessageError as error:
        await db.rollback()
        return speakable(f"Nothing was sent. {error}")
    return speakable(ALREADY_SENT if sent.duplicate else SENT)


async def send_request(db: AsyncSession, clock: Clock, *, call_id: int, request_id: str) -> str:
    """Send the stored words of `request_id`, verbatim. Commits; at most once per request."""
    request = await stored_request(db, call_id, request_id)
    if await _sent_proposal(db, request_id) is not None:
        raise BoundError(f"A confirmed wording of request {request_id} was already sent.")
    return await _send(db, clock, request.text, request_key(request_id))


async def propose_wording(
    db: AsyncSession, clock: Clock, *, call_id: int, request_id: str, text: str
) -> str:
    """Store a clearer wording next to the owner's words; nothing is sent. Commits."""
    request = await stored_request(db, call_id, request_id)
    text = text.strip()
    if not text or len(text) > MAX_CHARS:
        raise BoundError(f"A proposal is 1 to {MAX_CHARS} characters.")
    if await _queued(db, request_key(request_id)) or await _sent_proposal(db, request_id):
        raise BoundError(f"Request {request_id} was already sent to the CEO.")
    latest = await db.scalar(select(func.max(CallRequest.id)).where(CallRequest.call_id == call_id))
    proposal = WordingProposal(
        call_id=call_id,
        request_id=request.request_id,
        text=text,
        after_request_pk=latest or request.id,
        created_at=clock.now(),
    )
    db.add(proposal)
    await db.commit()
    return (
        f"Proposal {proposal.id} is stored and not sent. Read it to the owner word for word "
        f'and ask whether to send it: "{text}"'
    )


async def _pending_proposal(db: AsyncSession, call_id: int, proposal_id: int) -> WordingProposal:
    proposal = await db.get(WordingProposal, proposal_id)
    if proposal is None or proposal.call_id != call_id:
        raise BoundError(f"Proposal {proposal_id} is not part of this call.")
    if proposal.status is not ProposalStatus.PENDING:
        raise BoundError(f"Proposal {proposal_id} is already {proposal.status}.")
    return proposal


async def confirm_wording(
    db: AsyncSession, clock: Clock, *, call_id: int, proposal_id: int, request_id: str
) -> str:
    """Send or reject a proposal by the owner's answer in `request_id`. Commits.

    The answer must be a request stored after the proposal, so the owner heard it first. A
    no rejects it and sends nothing; anything short of a clear yes leaves it unsent.
    """
    proposal = await _pending_proposal(db, call_id, proposal_id)
    answer = await stored_request(db, call_id, request_id)
    if answer.id <= proposal.after_request_pk:
        raise BoundError(
            f"Request {request_id} came before the owner heard proposal {proposal_id}."
        )
    if _REJECT.search(answer.text):
        proposal.status = ProposalStatus.REJECTED
    elif _CONFIRM.search(answer.text):
        proposal.status = ProposalStatus.SENT
    else:
        raise BoundError(f"The owner did not clearly confirm proposal {proposal_id}.")
    proposal.decided_by_request_id = answer.request_id
    proposal.decided_at = clock.now()
    if proposal.status is ProposalStatus.REJECTED:
        await db.commit()
        return f"Proposal {proposal_id} is rejected. Nothing was sent."
    if await _queued(db, request_key(proposal.request_id)):
        raise BoundError(f"Request {proposal.request_id} was already sent to the CEO as spoken.")
    # The proposal is marked sent in the same commit that queues it for the CEO.
    return await _send(db, clock, proposal.text, proposal_key(proposal.id))
