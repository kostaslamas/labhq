"""Readings land where ADR 0003 puts them: USD in cost_events, the rest in usage_readings."""

import json
from decimal import Decimal

from sqlalchemy import select

from labhq.db.models import CostEvent, UsageReading
from labhq.usage.record import ReadingContext, record_failure, record_readings
from labhq.usage.schema import Reading, UsageUnit
from labhq.usage.statusline import statusline_readings
from tests.scheduler.conftest import World
from tests.usage.extracting import FIXTURES


def _context(world: World) -> ReadingContext:
    return ReadingContext(
        agent_id=world.agent_id,
        agent_kind="claude-code",
        run_id=None,
        project_id=world.project_id,
        source="screen",
        now=world.clock.now(),
    )


async def _rows(world: World) -> tuple[list[CostEvent], list[UsageReading]]:
    async with world.sessions() as db:
        costs = list(await db.scalars(select(CostEvent)))
        readings = list(await db.scalars(select(UsageReading)))
    return costs, readings


async def test_a_usd_reading_writes_one_cost_event_in_micros(world: World) -> None:
    async with world.sessions() as db:
        record_readings(db, _context(world), [Reading(unit=UsageUnit.USD, value=Decimal("0.07"))])
        await db.commit()

    costs, readings = await _rows(world)
    assert [(c.cost_micros, c.agent_id, c.project_id) for c in costs] == [
        (70_000, world.agent_id, world.project_id)
    ]
    assert readings == []


async def test_a_percent_reading_writes_one_usage_reading(world: World) -> None:
    reading = Reading(unit=UsageUnit.PERCENT, value=Decimal("23.5"), window="five_hour")
    async with world.sessions() as db:
        record_readings(db, _context(world), [reading])
        await db.commit()

    costs, readings = await _rows(world)
    assert costs == []
    assert [(r.unit, r.window, r.value, r.agent_kind, r.error) for r in readings] == [
        ("percent", "five_hour", 23.5, "claude-code", None)
    ]


async def test_a_failed_reading_is_recorded_without_a_value(world: World) -> None:
    async with world.sessions() as db:
        record_failure(db, _context(world), "value 33 does not appear in the captured text")
        await db.commit()

    _, (row,) = await _rows(world)
    assert row.value is None
    assert row.unit is None
    assert row.error is not None and "33" in row.error


def _statusline(name: str) -> dict[str, object]:
    document: dict[str, object] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return document


def test_the_statusline_gives_both_windows_and_the_session_cost() -> None:
    readings = statusline_readings(_statusline("statusline_with_rate_limits.json"))

    assert [(r.unit, r.window, r.value) for r in readings] == [
        (UsageUnit.PERCENT, "five_hour", Decimal("23.5")),
        (UsageUnit.PERCENT, "seven_day", Decimal("41.2")),
        (UsageUnit.USD, "session", Decimal("0.01234")),
    ]
    assert readings[0].resets_at is not None
    assert readings[0].resets_at.isoformat() == "2026-10-03T16:00:00+00:00"


def test_without_rate_limits_there_is_no_plan_reading_and_never_a_zero() -> None:
    readings = statusline_readings(_statusline("statusline_without_rate_limits.json"))

    assert [r.unit for r in readings] == [UsageUnit.USD]


def test_an_absent_window_is_no_reading() -> None:
    readings = statusline_readings(_statusline("statusline_one_window.json"))

    assert [r.window for r in readings] == ["seven_day"]


def test_malformed_fields_are_ignored_not_zeroed() -> None:
    document = {"rate_limits": {"five_hour": {"used_percentage": "lots"}}, "cost": None}

    assert statusline_readings(document) == []
