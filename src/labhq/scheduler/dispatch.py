"""Turn one pending wakeup into a queued run that holds its task, or leave it waiting.

Everything here happens in one transaction: the run is queued, the task checked out and
the wakeup marked dispatched together, or not at all. A wakeup that cannot start yet
(agent inactive or at its concurrency limit, task held by another run) stays pending
and is tried again on the next tick. One the budget stops is refused.

An agent kind past labhq's share of its plan window (ADR 0003) also leaves the wakeup
pending, so the work resumes on the first tick after the window resets, or moves at once
to the agent's fallback kind when that one is free.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.adapters.kinds import UnknownAgentChoiceError, choice_named
from labhq.budgets import BudgetSettings, Decision, check
from labhq.ceosessions import CEO_ROLE
from labhq.clock import Clock
from labhq.db.enums import AgentStatus, RunStatus, TaskStatus, WakeupSource, WakeupStatus
from labhq.db.models import Agent, Run, Task, WakeupRequest
from labhq.scheduler.admission import Admission
from labhq.scheduler.checkout import checkout
from labhq.scheduler.reaper import LIVE_STATUSES
from labhq.scheduler.settings import AgentLimits, SchedulerSettings
from labhq.scheduler.sources import SourceRegistry
from labhq.usage import UsageSettings, check_agent
from labhq.usage.plan import FALLBACK_ADAPTER_KEY, agent_kind, fallback_kind

# Sessions do not move between CLIs; the fallback starts from what the task left behind.
TAKEOVER_NOTE = (
    "You take this task over because the primary agent kind is unavailable or "
    "reached its plan limit. "
    "Start from the task status file and the work already in this workspace."
)


class Verdict(StrEnum):
    QUEUED = "queued"
    AGENT_INACTIVE = "agent_inactive"
    AT_CONCURRENCY = "at_concurrency"
    # The machine-wide cap on active runs, or the free-memory floor; both are retried.
    AT_CAPACITY = "at_capacity"
    LOW_MEMORY = "low_memory"
    TASK_HELD = "task_held"
    BUDGET_STOP = "budget_stop"
    # The agent kind is past its plan window share and has no free fallback; retried.
    PLAN_PAUSED = "plan_paused"
    # Another dispatcher took or refused the wakeup first.
    GONE = "gone"


_REFUSALS = {"capacity": Verdict.AT_CAPACITY, "low_memory": Verdict.LOW_MEMORY}


@dataclass(frozen=True)
class Dispatch:
    verdict: Verdict
    run_id: int | None = None
    agent_id: int | None = None
    task_id: int | None = None
    prompt: str = ""
    timeout_seconds: int = 0
    # Laid over `agents.config` for this run, e.g. the fallback agent kind.
    config: dict[str, Any] = field(default_factory=dict)
    adapter: str | None = None


async def pending_wakeup_ids(session: AsyncSession) -> list[int]:
    """Pending wakeups in start order: higher task priority first, then oldest first."""
    rows = await session.scalars(
        select(WakeupRequest.id)
        .outerjoin(Task, Task.id == WakeupRequest.task_id)
        .where(WakeupRequest.status == WakeupStatus.PENDING)
        .order_by(func.coalesce(Task.priority, 0).desc(), WakeupRequest.id)
    )
    return list(rows)


async def dispatch_one(
    session: AsyncSession,
    wakeup_id: int,
    clock: Clock,
    *,
    sources: SourceRegistry,
    settings: SchedulerSettings,
    budget_settings: BudgetSettings | None,
    usage_settings: UsageSettings | None = None,
    admission: Admission | None = None,
) -> Dispatch:
    """Try to queue a run for `wakeup_id`. Commits on success and on refusal."""
    request = await session.get_one(WakeupRequest, wakeup_id, populate_existing=True)
    if request.status is not WakeupStatus.PENDING:
        return Dispatch(Verdict.GONE)
    agent = await session.get_one(Agent, request.agent_id)
    if agent.status is not AgentStatus.ACTIVE:
        return Dispatch(Verdict.AGENT_INACTIVE)
    limits = AgentLimits.from_config(agent.config, settings)
    concurrency = 1 if agent.role == CEO_ROLE else limits.max_concurrency
    if await _live_runs(session, agent.id) >= concurrency:
        return Dispatch(Verdict.AT_CONCURRENCY)
    if admission is not None and (refused := await admission.refusal(session)) is not None:
        # Commit the owner's low-memory notice; the wakeup itself stays pending.
        await session.commit()
        return Dispatch(_REFUSALS[refused])

    # Plan §7 rule 3: checked at enqueue and again here, since spend moves in between.
    budget = await check(session, agent.id, clock, budget_settings)
    now = clock.now()
    if budget.decision is Decision.STOP:
        request.status = WakeupStatus.REFUSED
        request.updated_at = now
        await session.commit()
        return Dispatch(Verdict.BUDGET_STOP)

    overrides = await _plan_overrides(session, agent, clock, usage_settings)
    if overrides is None:
        # Commit the owner's notification; the wakeup itself stays pending.
        await session.commit()
        return Dispatch(Verdict.PLAN_PAUSED)

    selected_adapter = agent.config.get(FALLBACK_ADAPTER_KEY) if overrides else None
    if not isinstance(selected_adapter, str) or not selected_adapter:
        selected_adapter = agent.adapter
    run = Run(
        agent_id=agent.id,
        task_id=request.task_id,
        adapter=selected_adapter,
        status=RunStatus.QUEUED,
        created_at=now,
    )
    session.add(run)
    await session.flush()
    if request.task_id is not None and not await checkout(session, request.task_id, run.id):
        await session.rollback()
        return Dispatch(Verdict.TASK_HELD)
    task = await session.get(Task, request.task_id) if request.task_id is not None else None
    if (
        task is not None
        and task.assignee_id == agent.id
        and task.status in {TaskStatus.BACKLOG, TaskStatus.TODO}
    ):
        task.status = TaskStatus.IN_PROGRESS
        task.updated_at = now
    if not await _mark_dispatched(session, wakeup_id, run.id, now):
        await session.rollback()
        return Dispatch(Verdict.GONE)
    await session.commit()

    # Read after the commit, so wakeups merged up to now are in the brief.
    await session.refresh(request)
    task = await session.get(Task, request.task_id) if request.task_id is not None else None
    prompt = sources.handler(request.source).prompt(request, task)
    return Dispatch(
        Verdict.QUEUED,
        run_id=run.id,
        agent_id=agent.id,
        task_id=request.task_id,
        prompt=(
            f"{prompt}\n{TAKEOVER_NOTE}"
            if overrides and request.source is not WakeupSource.OWNER_MESSAGE
            else prompt
        ),
        timeout_seconds=limits.timeout_seconds,
        config=overrides,
        adapter=selected_adapter,
    )


async def _plan_overrides(
    session: AsyncSession, agent: Agent, clock: Clock, settings: UsageSettings | None
) -> dict[str, Any] | None:
    """{} to run as configured, the fallback kind to run on instead, or None to wait."""
    plan = await check_agent(session, agent, clock, settings)
    fallback = fallback_kind(agent.config)
    primary_missing = fallback is not None and not _kind_installed(
        agent_kind(agent.adapter, agent.config)
    )
    if plan.decision is not Decision.STOP and not primary_missing:
        return {}
    if fallback is None:
        return None
    if not _kind_installed(fallback):
        return None
    other = await check_agent(session, agent, clock, settings, kind=fallback)
    return None if other.decision is Decision.STOP else {"agent": fallback}


def _kind_installed(name: str) -> bool:
    try:
        choice = choice_named(name)
    except UnknownAgentChoiceError:
        # Custom adapters and test doubles manage their own availability.
        return True
    return choice.found() is not None


async def _live_runs(session: AsyncSession, agent_id: int) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(Run)
        .where(Run.agent_id == agent_id, Run.status.in_(LIVE_STATUSES))
    )
    return count or 0


async def _mark_dispatched(
    session: AsyncSession, wakeup_id: int, run_id: int, now: datetime
) -> bool:
    result = await session.execute(
        update(WakeupRequest)
        .where(WakeupRequest.id == wakeup_id, WakeupRequest.status == WakeupStatus.PENDING)
        .values(status=WakeupStatus.DISPATCHED, run_id=run_id, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]
