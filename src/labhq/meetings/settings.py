"""Meeting settings, read from `LABHQ_MEETINGS_*` environment variables."""

from functools import lru_cache

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


@lru_cache(maxsize=1)
def get_meeting_settings() -> MeetingSettings:
    return MeetingSettings()
