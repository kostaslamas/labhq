"""Hand the owner's words to an agent at the end of its current turn.

A delivery is a wakeup carrying the words, never a keystroke into a running turn: the
scheduler starts the agent's next run with them in its brief. Every delivery leaves a
`deliveries` row (ADR 0004). The words are stored and queued exactly as given.

Wakeups for one agent and task coalesce, and a merged wakeup's reason is dropped from the
brief. The words must survive that, so a coalesced delivery appends them to the request
that carries the work.

`deliver` flushes but never commits: the caller owns the transaction.
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from labhq.budgets import Decision
from labhq.clock import Clock
from labhq.db.enums import WakeupSource
from labhq.db.models import Delivery
from labhq.scheduler import Outcome, Wakeup, enqueue


@dataclass(frozen=True)
class DeliveryResult:
    # None when the scheduler refused the wakeup (the agent is over budget): nothing was
    # delivered, so nothing is recorded as delivered.
    delivery: Delivery | None
    outcome: Outcome


def _source_for(task_id: int | None) -> WakeupSource:
    # Existing sources only: a task wakeup is the comment kind, a task-less one a meeting.
    return WakeupSource.COMMENT if task_id is not None else WakeupSource.MEETING


async def deliver(
    db: AsyncSession,
    clock: Clock,
    *,
    call_id: int,
    request_id: str,
    agent_id: int,
    task_id: int | None,
    text: str,
    label: str,
) -> DeliveryResult:
    """Queue `text` for `agent_id`, introduced by `label`, and record the delivery."""
    reason = f"{label}: {text}"
    result = await enqueue(
        db,
        Wakeup(
            agent_id=agent_id,
            source=_source_for(task_id),
            idempotency_key=f"delivery:{request_id}:{label}:agent:{agent_id}",
            task_id=task_id,
            reason=reason,
        ),
        clock,
    )
    if result.outcome is Outcome.REFUSED or (
        result.budget is not None and result.budget.decision is Decision.STOP
    ):
        return DeliveryResult(None, result.outcome)
    if result.outcome is Outcome.COALESCED:
        result.request.reason = f"{result.request.reason}\n{reason}".strip()
    delivery = Delivery(
        call_id=call_id,
        request_id=request_id,
        recipient_agent_id=agent_id,
        text=text,
        interrupted=False,
        created_at=clock.now(),
    )
    db.add(delivery)
    await db.flush()
    return DeliveryResult(delivery, result.outcome)
