"""Budget periods: where the current period starts, as a registry keyed by period name."""

from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum

from labhq.clock import ensure_utc


class BudgetPeriod(StrEnum):
    MONTH = "month"
    LIFETIME = "lifetime"


_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _lifetime_start(_now: datetime) -> datetime:
    return _EPOCH


_PERIOD_STARTS: dict[BudgetPeriod, Callable[[datetime], datetime]] = {
    BudgetPeriod.MONTH: _month_start,
    BudgetPeriod.LIFETIME: _lifetime_start,
}


def period_start(period: BudgetPeriod, now: datetime) -> datetime:
    """The UTC instant the period containing `now` began."""
    return _PERIOD_STARTS[period](ensure_utc(now))
