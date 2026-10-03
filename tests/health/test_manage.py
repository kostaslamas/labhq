"""Rule management: reasons are mandatory, params are validated, disabled rules stay quiet."""

from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.clock import FakeClock
from labhq.db.enums import HealthRuleAction, IncidentStatus
from labhq.db.models import HealthRule, Incident
from labhq.health.incidents import evaluate_rules
from labhq.health.manage import RuleError, add_rule, list_rules, set_enabled, tune_rule
from tests.health.factories import add_host, add_samples

CPU_OVER_90 = {"metric": "cpu.percent", "comparison": ">", "value": 90}
AGENT = "agent:7 IT"


async def _add(session: AsyncSession, clock: FakeClock, **overrides: Any) -> HealthRule:
    fields: dict[str, Any] = {
        "rule_type": "threshold",
        "params": CPU_OVER_90,
        "action": HealthRuleAction.NOTIFY,
        "reason": "Builds stall when the CPU is pinned",
        "created_by": AGENT,
    }
    return await add_rule(session, clock, **{**fields, **overrides})


@pytest.mark.parametrize("reason", ["", "   "])
async def test_a_rule_without_a_reason_is_refused(
    session: AsyncSession, clock: FakeClock, reason: str
) -> None:
    with pytest.raises(RuleError, match="reason"):
        await _add(session, clock, reason=reason)
    assert (await session.scalars(select(HealthRule))).all() == []


async def test_a_rule_without_a_creator_is_refused(session: AsyncSession, clock: FakeClock) -> None:
    with pytest.raises(RuleError, match="creator"):
        await _add(session, clock, created_by=" ")


async def test_an_added_rule_is_listed_with_its_reason_and_creator(
    session: AsyncSession, clock: FakeClock
) -> None:
    rule = await _add(session, clock, name="cpu pinned", action=HealthRuleAction.TICKET)

    [view] = await list_rules(session)

    assert view.rule.id == rule.id
    assert (view.rule.type, view.rule.name, view.rule.action) == (
        "threshold",
        "cpu pinned",
        HealthRuleAction.TICKET,
    )
    assert view.rule.reason == "Builds stall when the CPU is pinned"
    assert view.rule.created_by == AGENT
    assert view.rule.enabled
    assert view.rule.params["duration_seconds"] == 0.0
    assert view.latest is None


async def test_the_listing_shows_the_latest_incident(
    session: AsyncSession, clock: FakeClock
) -> None:
    host = await add_host(session, clock)
    await _add(session, clock)
    await add_samples(session, host, "cpu.percent", [(clock.now(), 97.0)])
    await evaluate_rules(session, clock)

    [view] = await list_rules(session)

    assert view.latest is not None
    assert view.latest.status is IncidentStatus.OPEN


async def test_unknown_types_and_bad_params_are_refused(
    session: AsyncSession, clock: FakeClock
) -> None:
    with pytest.raises(RuleError, match="no rule type 'nope'"):
        await _add(session, clock, rule_type="nope")
    with pytest.raises(ValidationError):
        await _add(session, clock, params={"metric": "cpu.percent"})
    with pytest.raises(RuleError, match="no host 42"):
        await _add(session, clock, host_id=42)


async def test_disabling_through_the_service_stops_evaluation(
    session: AsyncSession, clock: FakeClock
) -> None:
    host = await add_host(session, clock)
    rule = await _add(session, clock)
    await set_enabled(session, clock, rule.id, enabled=False, by=AGENT)
    await add_samples(session, host, "cpu.percent", [(clock.now(), 97.0)])

    assert await evaluate_rules(session, clock) == []
    assert (await session.scalars(select(Incident))).all() == []

    await set_enabled(session, clock, rule.id, enabled=True, by="owner")
    assert len(await evaluate_rules(session, clock)) == 1


async def test_tuning_validates_params_and_replaces_the_reason(
    session: AsyncSession, clock: FakeClock
) -> None:
    rule = await _add(session, clock)
    clock.advance(60)

    tuned = await tune_rule(
        session,
        clock,
        rule.id,
        params={**CPU_OVER_90, "value": 95},
        reason="90 fires during nightly builds",
        by=AGENT,
    )

    assert tuned.params["value"] == 95
    assert tuned.reason == "90 fires during nightly builds"
    assert tuned.updated_at == clock.now()
    with pytest.raises(RuleError, match="reason"):
        await tune_rule(session, clock, rule.id, params=CPU_OVER_90, reason="", by=AGENT)
    with pytest.raises(ValidationError):
        await tune_rule(session, clock, rule.id, params={}, reason="why", by=AGENT)
    with pytest.raises(RuleError, match="no rule 99"):
        await set_enabled(session, clock, 99, enabled=False, by=AGENT)
