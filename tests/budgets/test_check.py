"""`check()` against the database: spend per agent and project, warnings once per period."""

from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.budgets import BudgetPeriod, BudgetSettings, Decision, UnknownAgentError, check
from labhq.clock import FakeClock
from labhq.db.enums import BudgetScope
from labhq.db.models import Agent, BudgetWarning, CostEvent, Project
from tests.db.factories import project_agent_task

DEFAULTS = BudgetSettings()


async def _setup(
    session: AsyncSession,
    clock: FakeClock,
    *,
    agent_budget: int | None = None,
    project_budget: int | None = None,
) -> tuple[Project, Agent]:
    project, agent, _ = await project_agent_task(session, clock)
    agent.budget_micros = agent_budget
    project.budget_micros = project_budget
    await session.flush()
    return project, agent


async def _spend(session: AsyncSession, clock: FakeClock, agent: Agent, *amounts: int) -> None:
    for amount in amounts:
        session.add(
            CostEvent(
                agent_id=agent.id,
                project_id=agent.project_id,
                cost_micros=amount,
                created_at=clock.now(),
            )
        )
    await session.flush()


async def _warnings(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(BudgetWarning)) or 0


async def test_at_100_percent_check_stops(session: AsyncSession, clock: FakeClock) -> None:
    _, agent = await _setup(session, clock, agent_budget=1_000_000)
    await _spend(session, clock, agent, 600_000, 400_000)
    result = await check(session, agent.id, clock, DEFAULTS)
    assert result.decision is Decision.STOP
    assert result.levels[0].spent_micros == 1_000_000


async def test_at_80_percent_check_warns_and_records_the_warning_once(
    session: AsyncSession, clock: FakeClock
) -> None:
    _, agent = await _setup(session, clock, agent_budget=1_000_000)
    await _spend(session, clock, agent, 800_000)

    first = await check(session, agent.id, clock, DEFAULTS)
    clock.advance(timedelta(hours=1))
    await _spend(session, clock, agent, 10_000)
    second = await check(session, agent.id, clock, DEFAULTS)

    assert (first.decision, second.decision) == (Decision.WARN, Decision.WARN)
    assert [first.levels[0].warning_recorded, second.levels[0].warning_recorded] == [True, False]
    assert await _warnings(session) == 1
    warning = await session.scalar(select(BudgetWarning))
    assert warning is not None
    assert (warning.scope, warning.scope_id) == (BudgetScope.AGENT, agent.id)
    assert (warning.spent_micros, warning.budget_micros) == (800_000, 1_000_000)
    assert warning.created_at == first.period_start.replace(day=2, hour=9)


async def test_below_80_percent_check_allows_and_records_nothing(
    session: AsyncSession, clock: FakeClock
) -> None:
    _, agent = await _setup(session, clock, agent_budget=1_000_000, project_budget=1_000_000)
    await _spend(session, clock, agent, 799_999)
    result = await check(session, agent.id, clock, DEFAULTS)
    assert result.decision is Decision.ALLOW
    assert await _warnings(session) == 0


async def test_a_new_period_warns_again_and_forgets_old_spend(
    session: AsyncSession, clock: FakeClock
) -> None:
    _, agent = await _setup(session, clock, agent_budget=1_000_000)
    await _spend(session, clock, agent, 900_000)
    assert (await check(session, agent.id, clock, DEFAULTS)).decision is Decision.WARN

    clock.advance(timedelta(days=30))  # 1 November
    assert (await check(session, agent.id, clock, DEFAULTS)).decision is Decision.ALLOW
    await _spend(session, clock, agent, 850_000)
    november = await check(session, agent.id, clock, DEFAULTS)

    assert november.decision is Decision.WARN
    assert november.levels[0].warning_recorded
    assert await _warnings(session) == 2


async def test_lifetime_period_keeps_counting(session: AsyncSession, clock: FakeClock) -> None:
    _, agent = await _setup(session, clock, agent_budget=1_000_000)
    await _spend(session, clock, agent, 900_000)
    clock.advance(timedelta(days=400))
    await _spend(session, clock, agent, 100_000)
    result = await check(session, agent.id, clock, BudgetSettings(period=BudgetPeriod.LIFETIME))
    assert result.decision is Decision.STOP


async def test_jumping_past_100_percent_still_records_the_warning(
    session: AsyncSession, clock: FakeClock
) -> None:
    _, agent = await _setup(session, clock, agent_budget=1_000_000)
    await _spend(session, clock, agent, 1_500_000)
    result = await check(session, agent.id, clock, DEFAULTS)
    assert result.decision is Decision.STOP
    assert result.levels[0].warning_recorded
    assert await _warnings(session) == 1


async def test_spend_is_summed_as_integer_micros(session: AsyncSession, clock: FakeClock) -> None:
    # A thousand one-micro runs: exact in integers, 0.0009999999999998899 as float dollars.
    _, agent = await _setup(session, clock, agent_budget=1_250)
    await _spend(session, clock, agent, *([1] * 1_000))
    result = await check(session, agent.id, clock, DEFAULTS)
    level = result.levels[0]
    assert type(level.spent_micros) is int
    assert type(level.budget_micros) is int
    assert level.spent_micros == 1_000
    assert result.decision is Decision.WARN


@pytest.mark.parametrize(
    ("agent_budget", "project_budget", "spend", "expected"),
    [
        (1_000_000, 10_000_000, 900_000, Decision.WARN),  # agent is stricter
        (10_000_000, 1_000_000, 1_000_000, Decision.STOP),  # project is stricter
        (1_000_000, 1_000_000, 850_000, Decision.WARN),
        (None, 1_000_000, 1_000_000, Decision.STOP),  # no agent limit, project applies
        (1_000_000, None, 1_000_000, Decision.STOP),  # no project limit, agent applies
        (None, None, 10**12, Decision.ALLOW),  # no limit anywhere
    ],
)
async def test_agent_and_project_both_apply_and_the_stricter_wins(
    session: AsyncSession,
    clock: FakeClock,
    agent_budget: int | None,
    project_budget: int | None,
    spend: int,
    expected: Decision,
) -> None:
    _, agent = await _setup(
        session, clock, agent_budget=agent_budget, project_budget=project_budget
    )
    await _spend(session, clock, agent, spend)
    result = await check(session, agent.id, clock, DEFAULTS)
    assert result.decision is expected
    assert [level.scope for level in result.levels] == [BudgetScope.AGENT, BudgetScope.PROJECT]


async def test_project_spend_includes_every_agent_in_the_project(
    session: AsyncSession, clock: FakeClock
) -> None:
    project, agent = await _setup(session, clock, project_budget=1_000_000)
    now = clock.now()
    colleague = Agent(
        project_id=project.id,
        role="worker",
        title="Colleague",
        adapter="fake",
        created_at=now,
        updated_at=now,
    )
    session.add(colleague)
    await session.flush()
    await _spend(session, clock, colleague, 700_000)
    await _spend(session, clock, agent, 100_000)

    result = await check(session, agent.id, clock, DEFAULTS)

    agent_level, project_level = result.levels
    assert (agent_level.spent_micros, project_level.spent_micros) == (100_000, 800_000)
    assert (agent_level.decision, project_level.decision) == (Decision.ALLOW, Decision.WARN)
    assert result.decision is Decision.WARN
    warning = await session.scalar(select(BudgetWarning))
    assert warning is not None
    assert (warning.scope, warning.scope_id) == (BudgetScope.PROJECT, project.id)


async def test_an_agent_without_a_project_has_only_its_own_level(
    session: AsyncSession, clock: FakeClock
) -> None:
    _, agent = await _setup(session, clock, agent_budget=1_000_000)
    agent.project_id = None
    await session.flush()
    await _spend(session, clock, agent, 100)
    result = await check(session, agent.id, clock, DEFAULTS)
    assert [level.scope for level in result.levels] == [BudgetScope.AGENT]


async def test_unknown_agent_is_an_error(session: AsyncSession, clock: FakeClock) -> None:
    with pytest.raises(UnknownAgentError):
        await check(session, 999, clock, DEFAULTS)
