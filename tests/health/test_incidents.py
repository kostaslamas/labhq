"""Violations open incidents, repeats do not duplicate them, recovery resolves them."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.clock import FakeClock
from labhq.db.enums import IncidentStatus
from labhq.db.models import Incident
from labhq.health.incidents import Transition, evaluate_rules
from tests.health.factories import add_host, add_rule, add_samples

CPU_OVER_90 = {"metric": "cpu.percent", "comparison": ">", "value": 90}


async def _incidents(session: AsyncSession) -> list[Incident]:
    return list((await session.scalars(select(Incident).order_by(Incident.id))).all())


async def test_a_violated_threshold_rule_opens_an_incident(
    session: AsyncSession, clock: FakeClock
) -> None:
    host = await add_host(session, clock)
    rule = await add_rule(session, clock, params=CPU_OVER_90)
    await add_samples(session, host, "cpu.percent", [(clock.now(), 97.0)])

    changes = await evaluate_rules(session, clock)
    await session.commit()

    [incident] = await _incidents(session)
    assert (incident.rule_id, incident.host_id) == (rule.id, host.id)
    assert incident.status is IncidentStatus.OPEN
    assert incident.opened_at == clock.now()
    assert incident.details["latest"] == {"": 97.0}
    assert [(c.transition, c.incident.id) for c in changes] == [(Transition.OPENED, incident.id)]


async def test_a_repeated_violation_does_not_open_a_second_incident(
    session: AsyncSession, clock: FakeClock
) -> None:
    host = await add_host(session, clock)
    await add_rule(session, clock, params=CPU_OVER_90)
    await add_samples(session, host, "cpu.percent", [(clock.now(), 97.0)])
    await evaluate_rules(session, clock)

    clock.advance(300)
    await add_samples(session, host, "cpu.percent", [(clock.now(), 99.0)])
    changes = await evaluate_rules(session, clock)

    assert changes == []
    assert len(await _incidents(session)) == 1


async def test_a_disabled_rule_opens_nothing(session: AsyncSession, clock: FakeClock) -> None:
    host = await add_host(session, clock)
    await add_rule(session, clock, params=CPU_OVER_90, enabled=False)
    await add_samples(session, host, "cpu.percent", [(clock.now(), 97.0)])

    assert await evaluate_rules(session, clock) == []
    assert await _incidents(session) == []


async def test_recovery_resolves_the_incident_and_a_new_violation_opens_another(
    session: AsyncSession, clock: FakeClock
) -> None:
    host = await add_host(session, clock)
    await add_rule(session, clock, params=CPU_OVER_90)
    await add_samples(session, host, "cpu.percent", [(clock.now(), 97.0)])
    await evaluate_rules(session, clock)

    clock.advance(300)
    await add_samples(session, host, "cpu.percent", [(clock.now(), 20.0)])
    [resolved] = await evaluate_rules(session, clock)
    assert resolved.transition is Transition.RESOLVED
    assert resolved.incident.status is IncidentStatus.RESOLVED
    assert resolved.incident.resolved_at == clock.now()

    clock.advance(300)
    await add_samples(session, host, "cpu.percent", [(clock.now(), 98.0)])
    [reopened] = await evaluate_rules(session, clock)
    assert reopened.transition is Transition.OPENED
    statuses = [incident.status for incident in await _incidents(session)]
    assert statuses == [IncidentStatus.RESOLVED, IncidentStatus.OPEN]


async def test_a_rule_bound_to_a_host_ignores_the_others(
    session: AsyncSession, clock: FakeClock
) -> None:
    watched = await add_host(session, clock, "watched")
    other = await add_host(session, clock, "other")
    await add_rule(session, clock, params=CPU_OVER_90, host=watched)
    for host in (watched, other):
        await add_samples(session, host, "cpu.percent", [(clock.now(), 97.0)])

    await evaluate_rules(session, clock)

    assert [incident.host_id for incident in await _incidents(session)] == [watched.id]


async def test_a_bad_rule_row_does_not_stop_the_others(
    session: AsyncSession, clock: FakeClock
) -> None:
    host = await add_host(session, clock)
    await add_rule(session, clock, params=CPU_OVER_90, rule_type="not-a-type")
    await add_rule(session, clock, params={"metric": "cpu.percent"})
    good = await add_rule(session, clock, params=CPU_OVER_90)
    await add_samples(session, host, "cpu.percent", [(clock.now(), 97.0)])

    changes = await evaluate_rules(session, clock)

    assert [change.rule.id for change in changes] == [good.id]
