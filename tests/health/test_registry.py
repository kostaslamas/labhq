"""A new rule type is a registration; the dispatch in `RuleRegistry.evaluate` stays as is."""

import inspect

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.clock import FakeClock
from labhq.db.models import Incident
from labhq.health import incidents, rules
from labhq.health.incidents import evaluate_rules
from labhq.health.rules import Evaluation, RuleContext, RuleRegistry, UnknownRuleTypeError
from tests.health.factories import add_host, add_rule


async def test_a_dummy_type_is_dispatched_after_registration_alone(
    session: AsyncSession, clock: FakeClock
) -> None:
    registry = RuleRegistry()
    seen: list[str] = []

    @registry.register("dummy")
    async def always_violated(context: RuleContext) -> Evaluation:
        seen.append(context.host.name)
        return Evaluation(violated=True, details={"why": "dummy"})

    host = await add_host(session, clock)
    await add_rule(session, clock, params={}, rule_type="dummy")

    [change] = await evaluate_rules(session, clock, registry)

    assert seen == [host.name]
    assert change.incident.details == {"why": "dummy"}
    assert len((await session.scalars(select(Incident))).all()) == 1


def test_dispatch_names_no_rule_type() -> None:
    # A new type must not need an edit here: the dispatch looks up, it does not branch.
    for function in (RuleRegistry.evaluate, incidents.evaluate_rules):
        assert '"threshold"' not in inspect.getsource(function)


def test_a_type_registers_once() -> None:
    with pytest.raises(ValueError, match="already registered"):
        rules.registry.register("threshold")(rules.evaluate_threshold)


async def test_an_unknown_type_is_an_error(session: AsyncSession, clock: FakeClock) -> None:
    host = await add_host(session, clock)
    rule = await add_rule(session, clock, params={}, rule_type="nope")
    with pytest.raises(UnknownRuleTypeError):
        await RuleRegistry().evaluate(RuleContext(session, rule, host, clock.now()))
