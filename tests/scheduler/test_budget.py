"""Budget at enqueue and again before start: stop refuses, warn proceeds and is recorded."""

from sqlalchemy import select

from labhq.db.enums import BudgetScope, WakeupStatus
from labhq.db.models import BudgetWarning, CostEvent, Project, Run
from labhq.scheduler import Outcome, Verdict
from tests.scheduler.conftest import World
from tests.scheduler.helpers import on_task, runs, set_agent, wakeups


async def _spend(world: World, micros: int) -> None:
    async with world.sessions() as db:
        db.add(
            CostEvent(
                agent_id=world.agent_id,
                project_id=world.project_id,
                cost_micros=micros,
                created_at=world.clock.now(),
            )
        )
        await db.commit()


async def _warnings(world: World) -> list[BudgetWarning]:
    async with world.sessions() as db:
        return list(await db.scalars(select(BudgetWarning)))


async def test_at_100_percent_the_wakeup_is_refused_and_no_run_starts(world: World) -> None:
    await set_agent(world, budget_micros=1_000_000)
    await _spend(world, 1_000_000)

    result = await world.scheduler.enqueue(on_task(world, "assign"))
    report = await world.scheduler.tick()

    assert result.outcome is Outcome.REFUSED
    assert result.request.status is WakeupStatus.REFUSED
    assert report.started == []
    assert await runs(world) == []


async def test_spend_that_reaches_100_percent_after_enqueue_stops_the_start(
    world: World,
) -> None:
    await set_agent(world, budget_micros=1_000_000)
    assert (await world.scheduler.enqueue(on_task(world, "assign"))).outcome is Outcome.CREATED
    await _spend(world, 1_000_000)

    report = await world.scheduler.tick()

    assert report.started == []
    assert list(report.waiting.values()) == [Verdict.BUDGET_STOP]
    assert [row.status for row in await wakeups(world)] == [WakeupStatus.REFUSED]
    assert await runs(world) == []


async def test_at_80_percent_the_run_starts_and_the_warning_is_recorded(world: World) -> None:
    await set_agent(world, budget_micros=1_000_000)
    await _spend(world, 800_000)

    result = await world.scheduler.enqueue(on_task(world, "assign"))
    report = await world.scheduler.tick()
    await world.scheduler.settle()

    assert result.outcome is Outcome.CREATED
    assert result.budget is not None and result.budget.levels[0].warning_recorded
    assert len(report.started) == 1
    (warning,) = await _warnings(world)
    assert (warning.scope, warning.scope_id) == (BudgetScope.AGENT, world.agent_id)
    assert (warning.spent_micros, warning.budget_micros) == (800_000, 1_000_000)
    async with world.sessions() as db:
        assert len(list(await db.scalars(select(Run)))) == 1


async def test_a_project_budget_stops_its_agents_too(world: World) -> None:
    async with world.sessions() as db:
        project = await db.get_one(Project, world.project_id)
        project.budget_micros = 500_000
        await db.commit()
    await _spend(world, 500_000)
    result = await world.scheduler.enqueue(on_task(world, "assign"))
    assert result.outcome is Outcome.REFUSED
