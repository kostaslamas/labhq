"""Meeting settings, read from `LABHQ_MEETINGS_*` environment variables."""

from functools import lru_cache
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class MeetingSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LABHQ_MEETINGS_", extra="ignore")

    # Seconds between two meetings of a kind, per kind. Empty means no meeting is requested on
    # a schedule: the owner has not decided a cadence (plan §13, question 3).
    cadence_seconds: dict[str, int] = Field(default_factory=dict)
    # One retry of the facilitator's minutes, then the meeting fails (issue #73).
    minutes_attempts: int = Field(default=2, gt=0)
    owner_name: str = Field(default="Owner", min_length=1)
    # Agent turns a decision room may take before it closes itself: a live thread has no
    # rounds, so this is what bounds its cost (issue #199).
    decision_turn_cap: int = Field(default=12, gt=0)
    # What one turn is priced at when a role has too few recorded turns; the UI labels it.
    decision_turn_estimate_micros: int = Field(default=200_000, gt=0)
    # Per role, overriding the constant above.
    role_turn_estimate_micros: dict[str, int] = Field(default_factory=dict)
    # The high end of a fallback turn, as a percentage of its low end.
    fallback_high_percent: int = Field(default=200, ge=100)
    # Recorded turns a role (or growth slopes) need before history replaces the constants.
    forecast_min_samples: int = Field(default=5, gt=0)
    # Extra cost of each turn over the one before, in thousandths of turn 1, assumed linear
    # until enough history measures it.
    growth_per_turn_permille: int = Field(default=100, ge=0)
    # The hard cap: a room stops once what it has cost reaches this (micro-USD, ADR 0002).
    decision_cost_cap_micros: int = Field(default=5_000_000, gt=0)
    # Run settings laid over the facilitator's own for the minutes. This is the seam for a
    # lighter model for the minutes (issue #198 decides the keys); empty changes nothing.
    minutes_config: dict[str, Any] = Field(default_factory=dict)


@lru_cache(maxsize=1)
def get_meeting_settings() -> MeetingSettings:
    return MeetingSettings()
