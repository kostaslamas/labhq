"""The trend rule forecasts when a metric crosses its limit from a linear fit."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.clock import FakeClock
from labhq.health.rule_types.trend import evaluate_trend, fit, seconds_to_limit
from labhq.health.rules import RuleContext
from tests.health.factories import add_host, add_rule, add_samples

DAY = timedelta(days=1)
DISK_FULL_IN_5_DAYS = {
    "metric": "disk.percent",
    "limit": 100,
    "within_days": 5,
    "window_seconds": 7 * 86400,
}


async def _evaluate(
    session: AsyncSession, clock: FakeClock, daily: list[float], params: dict[str, object]
) -> RuleContext:
    host = await add_host(session, clock)
    now = clock.now()
    points = [(now - (len(daily) - 1 - day) * DAY, value) for day, value in enumerate(daily)]
    await add_samples(session, host, "disk.percent", points, subject="/data")
    rule = await add_rule(session, clock, params=params, rule_type="trend")
    return RuleContext(session, rule, host, now)


async def test_a_rising_disk_is_full_within_the_horizon(
    session: AsyncSession, clock: FakeClock
) -> None:
    # One point a day for a week: 100% in about two days.
    context = await _evaluate(session, clock, [58, 64, 70, 76, 82, 88, 91], DISK_FULL_IN_5_DAYS)
    result = await evaluate_trend(context)
    assert result.violated
    forecast = result.details["forecasts"]["/data"]
    assert 0 < forecast["days_to_limit"] <= 5
    assert forecast["latest"] == 91


async def test_a_flat_disk_predicts_nothing(session: AsyncSession, clock: FakeClock) -> None:
    context = await _evaluate(session, clock, [91] * 7, DISK_FULL_IN_5_DAYS)
    assert not (await evaluate_trend(context)).violated


async def test_a_slow_rise_beyond_the_horizon_predicts_nothing(
    session: AsyncSession, clock: FakeClock
) -> None:
    # One point a day: 100% in about thirty days.
    context = await _evaluate(session, clock, [64, 65, 66, 67, 68, 69, 70], DISK_FULL_IN_5_DAYS)
    assert not (await evaluate_trend(context)).violated


async def test_a_falling_disk_predicts_nothing(session: AsyncSession, clock: FakeClock) -> None:
    context = await _evaluate(session, clock, [95, 90, 85, 80, 75, 70, 65], DISK_FULL_IN_5_DAYS)
    assert not (await evaluate_trend(context)).violated


async def test_too_few_samples_make_no_fit(session: AsyncSession, clock: FakeClock) -> None:
    context = await _evaluate(session, clock, [50, 99], DISK_FULL_IN_5_DAYS)
    assert not (await evaluate_trend(context)).violated


async def test_a_falling_metric_crosses_a_lower_limit(
    session: AsyncSession, clock: FakeClock
) -> None:
    params = {**DISK_FULL_IN_5_DAYS, "limit": 10}
    context = await _evaluate(session, clock, [40, 35, 30, 25, 20, 15, 12], params)
    assert (await evaluate_trend(context)).violated


def test_the_fit_is_exact_on_a_line() -> None:
    now = datetime(2026, 1, 10, tzinfo=UTC)
    points = [(now - timedelta(seconds=s), 100.0 - 2 * s) for s in (30, 20, 10, 0)]
    fitted = fit(points, now)
    assert fitted is not None
    slope, value_now = fitted
    assert slope == pytest.approx(2.0)
    assert value_now == pytest.approx(100.0)
    assert seconds_to_limit(2.0, 100.0, 120.0) == pytest.approx(10.0)
    assert seconds_to_limit(0.0, 100.0, 120.0) is None
    assert fit([(now, 1.0), (now, 2.0)], now) is None
