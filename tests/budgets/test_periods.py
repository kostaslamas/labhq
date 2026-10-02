"""Budget periods start at fixed UTC instants."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from labhq.budgets import BudgetPeriod, period_start


def test_month_starts_at_midnight_utc_on_the_first() -> None:
    now = datetime(2026, 10, 17, 13, 45, 12, 999, tzinfo=UTC)
    assert period_start(BudgetPeriod.MONTH, now) == datetime(2026, 10, 1, tzinfo=UTC)


def test_month_is_computed_in_utc_not_local_time() -> None:
    # 00:30 on 1 November in UTC+2 is still October in UTC.
    local = datetime(2026, 11, 1, 0, 30, tzinfo=timezone(timedelta(hours=2)))
    assert period_start(BudgetPeriod.MONTH, local) == datetime(2026, 10, 1, tzinfo=UTC)


def test_lifetime_never_rolls_over() -> None:
    assert period_start(BudgetPeriod.LIFETIME, datetime(2030, 5, 5, tzinfo=UTC)) == datetime(
        1970, 1, 1, tzinfo=UTC
    )


def test_every_period_has_a_start() -> None:
    now = datetime(2026, 10, 2, tzinfo=UTC)
    for period in BudgetPeriod:
        assert period_start(period, now) <= now


def test_naive_time_is_rejected() -> None:
    with pytest.raises(ValueError, match="naive"):
        period_start(BudgetPeriod.MONTH, datetime(2026, 10, 2))  # noqa: DTZ001
