"""IT department switches, read from `LABHQ_IT_*` environment variables."""

from datetime import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ItSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LABHQ_IT_", extra="ignore")

    title: str = Field(default="IT", min_length=1, max_length=200)
    # Plan §2.2: the agent wakes on a deviation and for one daily report, at this local time.
    report_time: time = time(8, 0)
    report_timezone: str = "UTC"
    # An incident opened within this window still wakes the agent if it already resolved,
    # so a short outage between two passes is not lost.
    incident_lookback_hours: float = Field(default=24.0, gt=0)

    @field_validator("report_timezone")
    @classmethod
    def _known_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(f"unknown time zone {value!r}") from error
        return value

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.report_timezone)
