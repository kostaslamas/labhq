"""Readings from the Claude Code statusline JSON, with no model call (ADR 0003).

Fields, from https://code.claude.com/docs/en/statusline (checked 2026-10-03):
`rate_limits.five_hour` and `rate_limits.seven_day`, each with `used_percentage` (0-100)
and `resets_at` (Unix epoch seconds), and `cost.total_cost_usd`. `rate_limits` appears only
for Pro and Max subscribers after the first API response, and each window may be absent:
an absent window or field is no reading, never zero.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from labhq.usage.schema import Reading, UsageUnit

PLAN_WINDOWS = ("five_hour", "seven_day")


def _number(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return Decimal(str(value))


def _instant(value: Any) -> datetime | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return datetime.fromtimestamp(value, tz=UTC)


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def statusline_readings(document: dict[str, Any]) -> list[Reading]:
    readings: list[Reading] = []
    limits = _object(document.get("rate_limits"))
    for window in PLAN_WINDOWS:
        entry = _object(limits.get(window))
        used = _number(entry.get("used_percentage"))
        if used is None:
            continue
        readings.append(
            Reading(
                unit=UsageUnit.PERCENT,
                value=used,
                window=window,
                resets_at=_instant(entry.get("resets_at")),
            )
        )
    cost = _number(_object(document.get("cost")).get("total_cost_usd"))
    if cost is not None:
        readings.append(Reading(unit=UsageUnit.USD, value=cost, window="session"))
    return readings
