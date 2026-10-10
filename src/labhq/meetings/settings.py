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
    # Shown to the owner when no past turn of the room's agents gives a better figure.
    decision_turn_estimate_micros: int = Field(default=200_000, gt=0)
    # Run settings laid over the facilitator's own for the minutes. This is the seam for a
    # cheaper model for the minutes (issue #198 decides the keys); empty changes nothing.
    minutes_config: dict[str, Any] = Field(default_factory=dict)


@lru_cache(maxsize=1)
def get_meeting_settings() -> MeetingSettings:
    return MeetingSettings()
