"""Codex usage goes through the extractor of ADR 0003: one fixture per `/status` screen.

Codex prints its plan windows as "N% left". The extractor copies that number as
`percent_left` and labhq turns it into the share used; a number that is not on the screen,
the share used included, is rejected and recorded as a failed reading, never as zero.
"""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from labhq.db.models import UsageReading
from labhq.usage.collect import UsageCollector
from labhq.usage.extractors import ExtractorRegistry
from labhq.usage.schema import ExtractionError, UsageUnit, check_extraction, parse_extraction
from tests.adapters.codex_harness import (
    CODEX_CONFIG,
    FakeCodex,
    fake_codex,  # noqa: F401  (fixture)
)
from tests.runs.conftest import World, sessions, world  # noqa: F401  (fixtures)
from tests.runs.helpers import events_of, use_adapter
from tests.usage.extracting import FakeExtractor
from tests.usage.plan_world import PLAN

FIXTURES = Path(__file__).with_name("fixtures") / "codex"
CAPTURED_AT = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)

# A well-behaved extractor's answer per screen, every number copied verbatim.
ANSWERS: dict[str, dict[str, Any]] = {
    "status_limits.txt": {
        "readings": [
            {"unit": "percent_left", "value": 55, "window": "5h"},
            {"unit": "percent_left", "value": 70, "window": "weekly"},
        ]
    },
    "status_monthly_limit.txt": {
        "readings": [{"unit": "percent_left", "value": 88, "window": "monthly"}]
    },
    # "Limits: data not available yet": no reading, which is not a zero.
    "status_missing_limits.txt": {"readings": []},
}
USED: dict[str, list[tuple[str, Decimal]]] = {
    "status_limits.txt": [("5h", Decimal(45)), ("weekly", Decimal(30))],
    "status_monthly_limit.txt": [("monthly", Decimal(12))],
    "status_missing_limits.txt": [],
}


def screen(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def checked(name: str, answer: dict[str, Any]) -> list[tuple[str | None, Decimal]]:
    extraction = check_extraction(
        parse_extraction(json.dumps(answer)),
        screen(name),
        captured_at=CAPTURED_AT,
        max_reset=timedelta(days=40),
    )
    assert {reading.unit for reading in extraction.readings} <= {UsageUnit.PERCENT}
    return [(reading.window, reading.value) for reading in extraction.readings]


def test_every_codex_fixture_has_an_answer() -> None:
    assert sorted(path.name for path in FIXTURES.glob("status_*.txt")) == sorted(ANSWERS)


@pytest.mark.parametrize("name", sorted(ANSWERS))
def test_a_captured_status_screen_yields_the_share_used(name: str) -> None:
    assert checked(name, ANSWERS[name]) == USED[name]


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        # The share used is arithmetic the extractor may not do: 45 is not on the screen.
        ({"unit": "percent", "value": 45, "window": "5h"}, "45 does not appear"),
        ({"unit": "percent_left", "value": 54, "window": "5h"}, "54 does not appear"),
        # 272 is on the screen (the context window), but no share is above the whole.
        ({"unit": "percent_left", "value": 272, "window": "5h"}, "more than the whole"),
    ],
    ids=["computed-used", "invented", "over-100"],
)
def test_an_invented_number_is_rejected(answer: dict[str, Any], message: str) -> None:
    with pytest.raises(ExtractionError, match=message):
        checked("status_limits.txt", {"readings": [answer]})


@pytest.fixture
async def codex_world(world: World, fake_codex: FakeCodex) -> World:  # noqa: F811
    world.registry.register("tmux", fake_codex.adapter, replace=True)
    await use_adapter(world, "tmux", CODEX_CONFIG)
    return world


async def collect(codex_world: World, tmp_path: Path, answer: dict[str, Any]) -> list[UsageReading]:
    run = await codex_world.service.execute(
        agent_id=codex_world.agent_id, task_id=codex_world.task_id, prompt="Fix it", cwd=tmp_path
    )
    (usage,) = [e for e in await events_of(codex_world, run.id) if e.kind == "usage_screen"]
    assert screen("status_limits.txt").strip().splitlines()[-1] in usage.payload["text"]
    extractors = ExtractorRegistry()
    extractors.register("model", FakeExtractor(answer))
    collector = UsageCollector(
        codex_world.sessions, clock=codex_world.clock, extractors=extractors, settings=PLAN
    )
    await collector.collect([run.id])
    async with codex_world.sessions() as db:
        return list(await db.scalars(select(UsageReading).order_by(UsageReading.id)))


async def test_the_usage_screen_of_a_codex_run_is_recorded_as_readings(
    codex_world: World, tmp_path: Path
) -> None:
    rows = await collect(codex_world, tmp_path, ANSWERS["status_limits.txt"])

    assert [(r.agent_kind, r.source, r.unit, r.window, r.value, r.error) for r in rows] == [
        ("codex", "screen", "percent", "5h", 45.0, None),
        ("codex", "screen", "percent", "weekly", 30.0, None),
    ]


async def test_an_invented_codex_reading_is_recorded_as_failed_never_zero(
    codex_world: World, tmp_path: Path
) -> None:
    invented = {"readings": [{"unit": "percent_left", "value": 54, "window": "5h"}]}

    (row,) = await collect(codex_world, tmp_path, invented)

    assert (row.agent_kind, row.value, row.unit) == ("codex", None, None)
    assert row.error is not None and "54 does not appear" in row.error
