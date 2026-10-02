"""The threshold rule type: metric, comparison, value and duration."""

from datetime import timedelta
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.clock import FakeClock
from labhq.health.rules import RuleContext, evaluate_threshold, registry
from tests.health.factories import add_host, add_rule, add_samples

MINUTE = timedelta(minutes=1)


async def _evaluate(session: AsyncSession, clock: FakeClock, params: dict[str, Any]) -> bool:
    host = await add_host(session, clock)
    rule = await add_rule(session, clock, params=params)
    return (await evaluate_threshold(RuleContext(session, rule, host, clock.now()))).violated


def test_threshold_is_registered() -> None:
    assert "threshold" in registry.types()


@pytest.mark.parametrize(
    ("comparison", "value", "violated"),
    [(">", 90.0, True), (">", 95.0, False), (">=", 95.0, True), ("<", 95.0, False)],
)
async def test_latest_sample_decides_without_a_duration(
    session: AsyncSession, clock: FakeClock, comparison: str, value: float, violated: bool
) -> None:
    host = await add_host(session, clock)
    await add_samples(session, host, "cpu.percent", [(clock.now() - MINUTE, 95.0)])
    rule = await add_rule(
        session, clock, params={"metric": "cpu.percent", "comparison": comparison, "value": value}
    )
    result = await evaluate_threshold(RuleContext(session, rule, host, clock.now()))
    assert result.violated is violated


async def test_no_samples_is_no_violation(session: AsyncSession, clock: FakeClock) -> None:
    assert not await _evaluate(
        session, clock, {"metric": "cpu.percent", "comparison": ">", "value": 0}
    )


async def test_duration_needs_the_condition_held_for_the_whole_window(
    session: AsyncSession, clock: FakeClock
) -> None:
    host = await add_host(session, clock)
    now = clock.now()
    params = {"metric": "cpu.percent", "comparison": ">", "value": 90, "duration_seconds": 600}
    rule = await add_rule(session, clock, params=params)

    async def violated() -> bool:
        return (await evaluate_threshold(RuleContext(session, rule, host, now))).violated

    # High for five minutes only: not yet ten.
    await add_samples(session, host, "cpu.percent", [(now - 5 * MINUTE, 99), (now, 99)])
    assert not await violated()
    # A dip inside the window breaks the streak.
    await add_samples(session, host, "cpu.percent", [(now - 10 * MINUTE, 99), (now - MINUTE, 50)])
    assert not await violated()


async def test_duration_held_throughout_is_a_violation(
    session: AsyncSession, clock: FakeClock
) -> None:
    host = await add_host(session, clock)
    now = clock.now()
    points = [(now - minutes * MINUTE, 97.0) for minutes in (12, 8, 4, 0)]
    await add_samples(session, host, "cpu.percent", points)
    params = {"metric": "cpu.percent", "comparison": ">", "value": 90, "duration_seconds": 600}
    rule = await add_rule(session, clock, params=params)
    result = await evaluate_threshold(RuleContext(session, rule, host, now))
    assert result.violated
    assert result.details["latest"] == {"": 97.0}


async def test_every_subject_is_watched_unless_one_is_named(
    session: AsyncSession, clock: FakeClock
) -> None:
    host = await add_host(session, clock)
    now = clock.now()
    await add_samples(session, host, "disk.percent", [(now, 50.0)], subject="/")
    await add_samples(session, host, "disk.percent", [(now, 93.0)], subject="/data")
    any_mount = await add_rule(
        session, clock, params={"metric": "disk.percent", "comparison": ">", "value": 90}
    )
    root_only = await add_rule(
        session,
        clock,
        params={"metric": "disk.percent", "comparison": ">", "value": 90, "subject": "/"},
    )
    first = await evaluate_threshold(RuleContext(session, any_mount, host, now))
    second = await evaluate_threshold(RuleContext(session, root_only, host, now))
    assert first.details["latest"] == {"/data": 93.0}
    assert not second.violated


async def test_other_hosts_samples_do_not_count(session: AsyncSession, clock: FakeClock) -> None:
    host = await add_host(session, clock, "one")
    other = await add_host(session, clock, "two")
    await add_samples(session, other, "cpu.percent", [(clock.now(), 99.0)])
    rule = await add_rule(
        session, clock, params={"metric": "cpu.percent", "comparison": ">", "value": 90}
    )
    result = await evaluate_threshold(RuleContext(session, rule, host, clock.now()))
    assert not result.violated


@pytest.mark.parametrize(
    "params",
    [
        {"metric": "cpu.percent", "comparison": "~", "value": 1},
        {"metric": "cpu.percent", "comparison": ">"},
        {"metric": "cpu.percent", "comparison": ">", "value": 1, "duration_seconds": -1},
        {"metric": "cpu.percent", "comparison": ">", "value": 1, "fix": "rm -rf /tmp"},
    ],
)
async def test_malformed_params_are_rejected(
    session: AsyncSession, clock: FakeClock, params: dict[str, Any]
) -> None:
    with pytest.raises(ValidationError):
        await _evaluate(session, clock, params)
