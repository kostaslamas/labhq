"""What an extractor must return, and the checks a reading passes before it counts.

The extractor answers with JSON. Pydantic checks its shape; then every number in it must
appear verbatim in the captured text, so a model that invents or computes a number is
caught. Reset times are the one exception: a screen says "resets in 2h", which the
extractor has to turn into an instant; those must lie after the capture and within a plan
window's reach. A reading that fails any check is recorded as failed, never as zero.
"""

import json
import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError


class UsageUnit(StrEnum):
    USD = "usd"
    PERCENT = "percent"
    TOKENS = "tokens"
    REQUESTS = "requests"


class Reading(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    unit: UsageUnit
    value: Decimal = Field(ge=0)
    window: str | None = Field(default=None, min_length=1, max_length=32)
    limit: Decimal | None = Field(default=None, ge=0)
    resets_at: AwareDatetime | None = None


class Extraction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    readings: list[Reading] = Field(default_factory=list)
    # True when the screen shows that the plan's limit is reached.
    limit_notice: bool = False
    limit_resets_at: AwareDatetime | None = None


class ExtractionError(ValueError):
    """The extractor's answer failed a check; the reading is recorded as failed."""


# Digits with optional thousands separators and decimals, not glued to a word or a dot.
_NUMBER = re.compile(r"(?<![\w.])\d{1,3}(?:,\d{3})+(?:\.\d+)?(?![\w])|(?<![\w.])\d+(?:\.\d+)?")


def numbers_in(text: str) -> set[Decimal]:
    found: set[Decimal] = set()
    for token in _NUMBER.findall(text):
        try:
            found.add(Decimal(token.replace(",", "")))
        except InvalidOperation:
            continue
    return found


def parse_extraction(raw: str) -> Extraction:
    """Parse the extractor's JSON; floats stay decimal so `12.50` is not `12.5000001`."""
    try:
        data = json.loads(_json_text(raw), parse_float=Decimal)
        return Extraction.model_validate(data)
    except (ValueError, ValidationError) as error:
        raise ExtractionError(f"the extractor's answer is not valid: {error}") from error


def check_extraction(
    extraction: Extraction, captured: str, *, captured_at: datetime, max_reset: timedelta
) -> Extraction:
    shown = numbers_in(captured)
    for reading in extraction.readings:
        for name, number in (("value", reading.value), ("limit", reading.limit)):
            if number is not None and number not in shown:
                raise ExtractionError(f"{name} {number} does not appear in the captured text")
        _check_reset(reading.resets_at, captured_at, max_reset)
    _check_reset(extraction.limit_resets_at, captured_at, max_reset)
    return extraction


def _check_reset(resets_at: datetime | None, captured_at: datetime, max_reset: timedelta) -> None:
    if resets_at is None:
        return
    if not captured_at < resets_at <= captured_at + max_reset:
        raise ExtractionError(f"reset time {resets_at.isoformat()} is not in a plan window")


def _json_text(raw: str) -> str:
    # A model may wrap its JSON in a code fence or a sentence; take the outermost object.
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in the answer")
    return raw[start : end + 1]
