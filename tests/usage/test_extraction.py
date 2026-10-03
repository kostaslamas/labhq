"""The extractor's answer passes the schema and the verbatim-number check, or fails loudly.

The screens under fixtures/ are representative captures of each CLI's usage output; the
manual check in docs/checks/tmux-adapter.md replaces them with real ones when a CLI changes.
"""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from labhq.usage.schema import (
    Extraction,
    ExtractionError,
    UsageUnit,
    check_extraction,
    numbers_in,
    parse_extraction,
)
from tests.usage.extracting import ANSWERS, FakeExtractor, screen

CAPTURED_AT = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)
MAX_RESET = timedelta(days=8)


async def _checked(fixture: str, answer: dict[str, Any] | str) -> Extraction:
    text = screen(fixture)
    raw = await FakeExtractor(answer).extract(text, "agent")
    return check_extraction(
        parse_extraction(raw), text, captured_at=CAPTURED_AT, max_reset=MAX_RESET
    )


@pytest.mark.parametrize("fixture", sorted(ANSWERS))
async def test_each_agents_captured_screen_passes_both_checks(fixture: str) -> None:
    extraction = await _checked(fixture, ANSWERS[fixture])

    assert extraction == parse_extraction(json.dumps(ANSWERS[fixture]))


async def test_the_codex_reading_keeps_its_windows_and_reset_times() -> None:
    extraction = await _checked("codex_status.txt", ANSWERS["codex_status.txt"])

    assert [(r.unit, r.value, r.window) for r in extraction.readings] == [
        (UsageUnit.PERCENT, Decimal(31), "5h"),
        (UsageUnit.PERCENT, Decimal(14), "weekly"),
    ]


async def test_an_invented_number_is_rejected() -> None:
    answer = {"readings": [{"unit": "percent", "value": 33, "window": "5h"}]}

    with pytest.raises(ExtractionError, match="33 does not appear"):
        await _checked("codex_status.txt", answer)


async def test_a_computed_number_is_rejected() -> None:
    # 4.2k tokens is 4200 only by arithmetic the extractor may not do.
    answer = {"readings": [{"unit": "tokens", "value": 4200, "window": "sent"}]}

    with pytest.raises(ExtractionError, match="4200"):
        await _checked("aider_reply.txt", answer)


async def test_an_invented_limit_is_rejected() -> None:
    answer = {"readings": [{"unit": "percent", "value": 31, "limit": 500}]}

    with pytest.raises(ExtractionError, match="limit 500"):
        await _checked("codex_status.txt", answer)


@pytest.mark.parametrize(
    "answer",
    [
        "no json at all",
        {"readings": [{"unit": "furlongs", "value": 31}]},
        {"readings": [{"unit": "percent", "value": -31}]},
        {"readings": [{"unit": "percent"}]},
        {"readings": [], "surprise": True},
        {"readings": [{"unit": "percent", "value": 31, "resets_at": "2026-10-02T17:42:00"}]},
    ],
    ids=["not-json", "unknown-unit", "negative", "no-value", "extra-key", "naive-reset"],
)
async def test_an_answer_outside_the_schema_is_rejected(answer: dict[str, Any] | str) -> None:
    with pytest.raises(ExtractionError):
        await _checked("codex_status.txt", answer)


@pytest.mark.parametrize(
    "resets_at", ["2026-10-02T08:00:00Z", "2026-11-30T00:00:00Z"], ids=["past", "too-far"]
)
async def test_a_reset_time_outside_a_plan_window_is_rejected(resets_at: str) -> None:
    answer = {"readings": [{"unit": "percent", "value": 31, "resets_at": resets_at}]}

    with pytest.raises(ExtractionError, match="not in a plan window"):
        await _checked("codex_status.txt", answer)


def test_numbers_are_read_with_separators_and_decimals() -> None:
    assert numbers_in("21,480 tokens, $0.07, 100.0% v2") >= {
        Decimal(21480),
        Decimal("0.07"),
        Decimal(100),
    }
