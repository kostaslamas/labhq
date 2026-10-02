"""Enqueue a wakeup: idempotent, budget-checked, coalesced into the agent's pending work.

Order matters. A known idempotency key returns its request before anything else, so a
retry neither spends a budget check nor bumps a counter. A budget `stop` is stored as a
refused request, so retrying it is refused again without asking twice. Otherwise the
wakeup merges into a pending request of the same agent and task when one exists, which is
how wakeups arriving during a run collapse into one (plan §7, rule 1).

Each function flushes but never commits: the caller owns the transaction.
"""

from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.budgets import BudgetSettings, Decision, check
from labhq.clock import Clock
from labhq.db.enums import WakeupStatus
from labhq.db.models import WakeupRequest
from labhq.scheduler.sources import Trigger, WakeupSources, WakeupSpec, default_sources


class EnqueueOutcome(StrEnum):
    CREATED = "created"
    COALESCED = "coalesced"
    DUPLICATE = "duplicate"
    REFUSED = "refused"


@dataclass(frozen=True, slots=True)
class Enqueued:
    outcome: EnqueueOutcome
    # The request that carries this wakeup's work: the merge target when coalesced.
    request_id: int
    # The row stored under the idempotency key.
    key_request_id: int
    # None for a duplicate, which skips the budget check.
    budget: Decision | None


async def wake(
    session: AsyncSession,
    trigger: Trigger,
    clock: Clock,
    *,
    sources: WakeupSources = default_sources,
    budget_settings: BudgetSettings | None = None,
) -> list[Enqueued]:
    specs = await sources.specs_for(session, trigger)
    return [await enqueue(session, spec, clock, budget_settings=budget_settings) for spec in specs]


async def enqueue(
    session: AsyncSession,
    spec: WakeupSpec,
    clock: Clock,
    *,
    budget_settings: BudgetSettings | None = None,
) -> Enqueued:
    existing = await _by_key(session, spec.idempotency_key)
    if existing is not None:
        return _duplicate(existing)

    budget = (await check(session, spec.agent_id, clock, budget_settings)).decision
    if budget is Decision.STOP:
        return await _insert(session, spec, clock, WakeupStatus.REFUSED, budget)

    target = await _pending_for(session, spec)
    if target is None:
        return await _insert(session, spec, clock, WakeupStatus.PENDING, budget)
    return await _coalesce(session, spec, clock, target, budget)


async def _coalesce(
    session: AsyncSession, spec: WakeupSpec, clock: Clock, target: int, budget: Decision
) -> Enqueued:
    # The key row goes in first: if a concurrent retry won the key, nothing was counted.
    stored = await _insert(
        session, spec, clock, WakeupStatus.COALESCED, budget, coalesced_into_id=target
    )
    if stored.outcome is EnqueueOutcome.DUPLICATE:
        return stored
    merged = await session.execute(
        update(WakeupRequest)
        .where(WakeupRequest.id == target, WakeupRequest.status == WakeupStatus.PENDING)
        .values(
            coalesced_count=WakeupRequest.coalesced_count + 1,
            updated_at=clock.now(),
        )
    )
    if merged.rowcount:  # type: ignore[attr-defined]
        return stored
    # The target was dispatched in between; this wakeup becomes pending work of its own.
    await session.execute(
        update(WakeupRequest)
        .where(WakeupRequest.id == stored.key_request_id)
        .values(status=WakeupStatus.PENDING, coalesced_into_id=None)
    )
    own = stored.key_request_id
    return Enqueued(EnqueueOutcome.CREATED, own, own, budget)


_OUTCOME_BY_STATUS = {
    WakeupStatus.PENDING: EnqueueOutcome.CREATED,
    WakeupStatus.COALESCED: EnqueueOutcome.COALESCED,
    WakeupStatus.REFUSED: EnqueueOutcome.REFUSED,
}


async def _insert(
    session: AsyncSession,
    spec: WakeupSpec,
    clock: Clock,
    status: WakeupStatus,
    budget: Decision,
    *,
    coalesced_into_id: int | None = None,
) -> Enqueued:
    now = clock.now()
    # The unique key settles concurrent enqueues: one insert wins, the rest read it back.
    row_id = await session.scalar(
        insert(WakeupRequest)
        .values(
            agent_id=spec.agent_id,
            task_id=spec.task_id,
            source=spec.source,
            reason=spec.reason,
            status=status,
            coalesced_count=0,
            idempotency_key=spec.idempotency_key,
            coalesced_into_id=coalesced_into_id,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
        .returning(WakeupRequest.id)
    )
    if row_id is None:
        existing = await _by_key(session, spec.idempotency_key)
        assert existing is not None
        return _duplicate(existing)
    work_id = coalesced_into_id if coalesced_into_id is not None else row_id
    return Enqueued(_OUTCOME_BY_STATUS[status], work_id, row_id, budget)


def _duplicate(row: WakeupRequest) -> Enqueued:
    work_id = row.coalesced_into_id if row.coalesced_into_id is not None else row.id
    return Enqueued(EnqueueOutcome.DUPLICATE, work_id, row.id, None)


async def _by_key(session: AsyncSession, key: str) -> WakeupRequest | None:
    return await session.scalar(select(WakeupRequest).where(WakeupRequest.idempotency_key == key))


async def _pending_for(session: AsyncSession, spec: WakeupSpec) -> int | None:
    # Per agent and task: merging work for another task into this one would lose it.
    return await session.scalar(
        select(WakeupRequest.id)
        .where(
            WakeupRequest.agent_id == spec.agent_id,
            WakeupRequest.task_id.is_(None)
            if spec.task_id is None
            else WakeupRequest.task_id == spec.task_id,
            WakeupRequest.status == WakeupStatus.PENDING,
        )
        .order_by(WakeupRequest.id)
        .limit(1)
    )
