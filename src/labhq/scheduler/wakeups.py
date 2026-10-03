"""Enqueue wakeups from any registered source: idempotent, coalesced, budget-checked.

`enqueue` flushes but never commits: the caller owns the transaction, as with
`labhq.budgets.check()`.

A wakeup that merges into a pending request still gets its own row, marked `cancelled`,
so its `idempotency_key` is taken: a retry of a merged wakeup is a duplicate, not a
second increment of `coalesced_count`.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.budgets import BudgetCheck, BudgetSettings, Decision, check
from labhq.clock import Clock
from labhq.db.enums import WakeupSource, WakeupStatus
from labhq.db.models import Agent, WakeupRequest
from labhq.scheduler.sources import SourceRegistry, default_sources
from labhq.usage import PlanCheck, UsageSettings, check_agent


@dataclass(frozen=True)
class Wakeup:
    agent_id: int
    source: WakeupSource
    # Chosen by the producer from what makes the event unique, e.g. "comment:42:agent:7".
    idempotency_key: str
    task_id: int | None = None
    reason: str = ""


class Outcome(StrEnum):
    CREATED = "created"
    COALESCED = "coalesced"
    DUPLICATE = "duplicate"
    REFUSED = "refused"


@dataclass(frozen=True)
class EnqueueResult:
    outcome: Outcome
    # The request that will carry this wakeup: the new one, the merge target, or the
    # earlier row with the same key.
    request: WakeupRequest
    # None for a duplicate: the first enqueue already checked.
    budget: BudgetCheck | None = None
    # A plan stop does not refuse: the wakeup waits for the window's reset (ADR 0003).
    plan: PlanCheck | None = None


async def enqueue(
    session: AsyncSession,
    wakeup: Wakeup,
    clock: Clock,
    *,
    sources: SourceRegistry = default_sources,
    budget_settings: BudgetSettings | None = None,
    usage_settings: UsageSettings | None = None,
) -> EnqueueResult:
    sources.handler(wakeup.source).validate(wakeup.task_id)
    existing = await _by_key(session, wakeup.idempotency_key)
    if existing is not None:
        return EnqueueResult(Outcome.DUPLICATE, existing)

    budget = await check(session, wakeup.agent_id, clock, budget_settings)
    if budget.decision is Decision.STOP:
        return await _insert(session, wakeup, clock, Outcome.REFUSED, budget)
    agent = await session.get_one(Agent, wakeup.agent_id)
    plan = await check_agent(session, agent, clock, usage_settings)
    result = await _enqueue_allowed(session, wakeup, clock, budget)
    return EnqueueResult(result.outcome, result.request, result.budget, plan)


async def _enqueue_allowed(
    session: AsyncSession, wakeup: Wakeup, clock: Clock, budget: BudgetCheck
) -> EnqueueResult:

    target = await _pending_for(session, wakeup.agent_id, wakeup.task_id)
    if target is None:
        return await _insert(session, wakeup, clock, Outcome.CREATED, budget)

    result = await _insert(
        session,
        wakeup,
        clock,
        Outcome.COALESCED,
        budget,
        reason_prefix=f"coalesced into #{target.id}: ",
    )
    if result.outcome is Outcome.DUPLICATE:
        return result
    await session.execute(
        update(WakeupRequest)
        .where(WakeupRequest.id == target.id)
        .values(
            coalesced_count=WakeupRequest.coalesced_count + 1,
            updated_at=clock.now(),
        )
    )
    await session.refresh(target)
    return EnqueueResult(Outcome.COALESCED, target, budget)


_STATUS_BY_OUTCOME: dict[Outcome, WakeupStatus] = {
    Outcome.CREATED: WakeupStatus.PENDING,
    Outcome.REFUSED: WakeupStatus.REFUSED,
    # The merged row only reserves the key; the target request carries the work.
    Outcome.COALESCED: WakeupStatus.CANCELLED,
}


async def _insert(
    session: AsyncSession,
    wakeup: Wakeup,
    clock: Clock,
    outcome: Outcome,
    budget: BudgetCheck,
    *,
    reason_prefix: str = "",
) -> EnqueueResult:
    now = clock.now()
    values: dict[str, Any] = {
        "agent_id": wakeup.agent_id,
        "task_id": wakeup.task_id,
        "source": wakeup.source,
        "reason": reason_prefix + wakeup.reason,
        "status": _STATUS_BY_OUTCOME[outcome],
        "idempotency_key": wakeup.idempotency_key,
        "created_at": now,
        "updated_at": now,
    }
    # The unique key settles a race between two enqueues of the same wakeup: one insert
    # wins and the other reads the winner back as a duplicate.
    inserted = await session.execute(
        insert(WakeupRequest)
        .values(**values)
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
    )
    row = await _by_key(session, wakeup.idempotency_key)
    assert row is not None
    if not inserted.rowcount:  # type: ignore[attr-defined]
        return EnqueueResult(Outcome.DUPLICATE, row)
    return EnqueueResult(outcome, row, budget)


async def _by_key(session: AsyncSession, key: str) -> WakeupRequest | None:
    return await session.scalar(
        select(WakeupRequest)
        .where(WakeupRequest.idempotency_key == key)
        .execution_options(populate_existing=True)
    )


async def _pending_for(
    session: AsyncSession, agent_id: int, task_id: int | None
) -> WakeupRequest | None:
    # Coalescing is per agent and task, so a merge never loses which task to work on.
    return await session.scalar(
        select(WakeupRequest)
        .where(
            WakeupRequest.agent_id == agent_id,
            WakeupRequest.task_id.is_not_distinct_from(task_id),
            WakeupRequest.status == WakeupStatus.PENDING,
        )
        .order_by(WakeupRequest.id)
        .limit(1)
    )
