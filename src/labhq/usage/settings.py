"""Plan usage thresholds and extraction settings, read from `LABHQ_*` (ADR 0003)."""

from functools import lru_cache
from typing import Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class UsageSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LABHQ_", extra="ignore")

    # labhq warns at this share of a plan window and starts no new run from the stop share,
    # leaving the rest of every window to the owner (owner decision, 2026-10-03).
    plan_usage_warn_percent: int = Field(default=50, gt=0, le=100)
    plan_usage_stop_percent: int = Field(default=70, gt=0, le=100)
    # A limit notice that names no reset time holds new runs for this long.
    plan_limit_hold_seconds: int = Field(default=3600, gt=0)
    # The extractor registry key, and the agent whose one-shot runs do the model extraction.
    usage_extractor: str = "model"
    usage_extractor_agent_id: int | None = None
    # A reset time further away than this is not a plan window; the reading is rejected.
    usage_max_reset_days: int = Field(default=8, gt=0)

    @model_validator(mode="after")
    def _warn_before_stop(self) -> Self:
        if self.plan_usage_warn_percent > self.plan_usage_stop_percent:
            raise ValueError("plan_usage_warn_percent must not exceed plan_usage_stop_percent")
        return self


@lru_cache(maxsize=1)
def get_usage_settings() -> UsageSettings:
    return UsageSettings()
