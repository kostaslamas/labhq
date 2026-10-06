"""A department's budget stops its agents like a project's does."""

from labhq.budgets import Decision, check
from labhq.db.enums import BudgetScope
from labhq.db.models import CostEvent, Run
from tests.departments.conftest import Research


async def test_a_department_over_its_budget_stops_its_agents(research: Research) -> None:
    org = research.org
    await org.call("set_budget", org.ceo, scope="department", id="Research", micros=1_000)
    async with org.sessions() as db:
        run = Run(agent_id=research.head, adapter="fake", created_at=org.clock.now())
        db.add(run)
        await db.flush()
        db.add(
            CostEvent(
                run_id=run.id,
                agent_id=research.head,
                cost_micros=1_000,
                created_at=org.clock.now(),
            )
        )
        await db.commit()
    async with org.sessions() as db:
        result = await check(db, research.head, org.clock)
    assert result.decision is Decision.STOP
    assert BudgetScope.DEPARTMENT in {level.scope for level in result.levels}
