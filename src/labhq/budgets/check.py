"""Budget check for an agent and its project, with the once-per-period warning record.

The scheduler calls `check()` at enqueue and again before a run starts (plan §7, rules 3
and 4). It flushes but never commits: the caller owns the transaction.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.budgets.decision import Decision, decide, require_micros, stricter
from labhq.budgets.periods import period_start
from labhq.budgets.settings import BudgetSettings, get_budget_settings
from labhq.clock import Clock
from labhq.db.enums import BudgetScope
from labhq.db.models import Agent, BudgetWarning, CostEvent, Project


class UnknownAgentError(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class LevelCheck:
    """One budget level and the numbers behind its decision."""

    scope: BudgetScope
    scope_id: int
    budget_micros: int | None
    spent_micros: int
    decision: Decision
    # True only on the check that recorded this period's warning.
    warning_recorded: bool


@dataclass(frozen=True, slots=True)
class BudgetCheck:
    decision: Decision
    period_start: datetime
    levels: tuple[LevelCheck, ...]


async def check(
    session: AsyncSession,
    agent_id: int,
    clock: Clock,
    settings: BudgetSettings | None = None,
) -> BudgetCheck:
    """Decide whether `agent_id` may start work; the stricter of agent and project wins."""
    settings = settings or get_budget_settings()
    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise UnknownAgentError(f"no agent with id {agent_id}")
    now = clock.now()
    start = period_start(settings.period, now)

    levels = [
        await _check_level(
            session,
            BudgetScope.AGENT,
            agent.id,
            agent.budget_micros,
            CostEvent.agent_id == agent.id,
            start,
            now,
            settings,
        )
    ]
    if agent.project_id is not None:
        project = await session.get(Project, agent.project_id)
        if project is not None:
            levels.append(
                await _check_level(
                    session,
                    BudgetScope.PROJECT,
                    project.id,
                    project.budget_micros,
                    CostEvent.project_id == project.id,
                    start,
                    now,
                    settings,
                )
            )
    return BudgetCheck(
        decision=stricter(*(level.decision for level in levels)),
        period_start=start,
        levels=tuple(levels),
    )


async def spent_micros(
    session: AsyncSession, scope_filter: ColumnElement[bool], since: datetime
) -> int:
    """Sum of `cost_events` matching `scope_filter` from `since`, summed in SQL as integers."""
    total = await session.scalar(
        select(func.coalesce(func.sum(CostEvent.cost_micros), 0)).where(
            scope_filter, CostEvent.created_at >= since
        )
    )
    return require_micros("spent_micros", total)


async def _check_level(
    session: AsyncSession,
    scope: BudgetScope,
    scope_id: int,
    budget_micros: int | None,
    scope_filter: ColumnElement[bool],
    start: datetime,
    now: datetime,
    settings: BudgetSettings,
) -> LevelCheck:
    spent = await spent_micros(session, scope_filter, start)
    decision = decide(spent, budget_micros, settings)
    # A jump straight past 100% still crossed 80%, so STOP records the warning as well.
    recorded = False
    if budget_micros is not None and decision is not Decision.ALLOW:
        recorded = await _record_warning(session, scope, scope_id, start, spent, budget_micros, now)
    return LevelCheck(scope, scope_id, budget_micros, spent, decision, recorded)


async def _record_warning(
    session: AsyncSession,
    scope: BudgetScope,
    scope_id: int,
    start: datetime,
    spent: int,
    budget: int,
    now: datetime,
) -> bool:
    # The unique key makes concurrent checks race safely: one insert wins, the rest no-op.
    result = await session.execute(
        insert(BudgetWarning)
        .values(
            scope=scope,
            scope_id=scope_id,
            period_start=start,
            spent_micros=spent,
            budget_micros=budget,
            created_at=now,
        )
        .on_conflict_do_nothing(index_elements=["scope", "scope_id", "period_start"])
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]
