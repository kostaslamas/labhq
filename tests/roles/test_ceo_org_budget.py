"""`set_budget` stays at or below the owner's ceiling and never touches the CEO's own."""

import pytest

from labhq.ceoorg.budget import BudgetRefusedError, BudgetScope, set_budget
from labhq.ceoorg.settings import CeoSettings
from labhq.db.models import Agent, Project
from tests.roles.conftest import CEILING, Org


async def test_a_budget_at_or_below_the_ceiling_is_set_for_an_agent_and_a_project(
    org: Org,
) -> None:
    agent = await org.call("set_budget", org.ceo, scope="agent", id=org.worker, micros=CEILING)
    project = await org.call("set_budget", org.ceo, scope="project", id="shop", micros=1_000_000)

    assert (await org.get(Agent, org.worker)).budget_micros == CEILING
    assert (await org.get(Project, org.shop)).budget_micros == 1_000_000
    assert "is now $5.0000 (was none)" in agent
    assert "project shop is now $1.0000" in project


async def test_a_budget_above_the_ceiling_is_refused_and_changes_nothing(org: Org) -> None:
    answer = await org.call("set_budget", org.ceo, scope="project", id=org.shop, micros=CEILING + 1)

    assert answer.startswith("Refused:")
    assert "above the owner's ceiling" in answer
    assert (await org.get(Project, org.shop)).budget_micros is None


async def test_the_ceo_cannot_set_its_own_budget(org: Org) -> None:
    answer = await org.call("set_budget", org.ceo, scope="agent", id=org.ceo, micros=1)

    assert answer.startswith("Refused:")
    assert "CEO's own budget" in answer
    assert (await org.get(Agent, org.ceo)).budget_micros is None


async def test_a_budget_must_be_positive(org: Org) -> None:
    answer = await org.call("set_budget", org.ceo, scope="agent", id=org.worker, micros=0)

    assert answer.startswith("Invalid arguments")


async def test_without_a_ceiling_no_budget_can_be_set(org: Org) -> None:
    async with org.sessions() as db:
        with pytest.raises(BudgetRefusedError, match="no budget ceiling"):
            await set_budget(
                db,
                org.clock,
                CeoSettings(),
                caller=org.ceo,
                scope=BudgetScope.AGENT,
                target=str(org.worker),
                micros=1,
            )


def test_the_ceiling_comes_from_the_owners_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LABHQ_CEO_BUDGET_CEILING_MICROS", "2500000")

    assert CeoSettings().budget_ceiling_micros == 2_500_000


def test_no_tool_writes_the_ceiling(org: Org) -> None:
    for spec in org.tools:
        assert "ceiling" not in spec.input_model.model_json_schema().get("properties", {})
