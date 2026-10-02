"""Scheduler limits: process-wide defaults from `LABHQ_SCHEDULER_*`, per agent from config."""

from dataclasses import dataclass
from datetime import timedelta
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SchedulerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LABHQ_SCHEDULER_", extra="ignore")

    # A low default keeps one agent from multiplying its spend unnoticed (plan §7, rule 2).
    default_concurrency: int = Field(default=1, ge=1)
    default_timeout_seconds: int = Field(default=3600, gt=0)
    # A run with no event for this long is presumed dead (plan §7, rule 5).
    heartbeat_limit_seconds: int = Field(default=900, gt=0)
    # Time an interrupted run gets to report its result before it is closed by force.
    stop_grace_seconds: int = Field(default=30, ge=0)

    @property
    def heartbeat_limit(self) -> timedelta:
        return timedelta(seconds=self.heartbeat_limit_seconds)

    @property
    def stop_grace(self) -> timedelta:
        return timedelta(seconds=self.stop_grace_seconds)


@lru_cache(maxsize=1)
def get_scheduler_settings() -> SchedulerSettings:
    return SchedulerSettings()


class AgentScheduleConfig(BaseModel):
    """The keys of `agents.config` the scheduler reads; other keys belong to other modules."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    concurrency: int | None = Field(default=None, ge=1)
    timeout_seconds: int | None = Field(default=None, gt=0)


@dataclass(frozen=True, slots=True)
class AgentLimits:
    concurrency: int
    timeout: timedelta


def limits_for(config: dict[str, Any], settings: SchedulerSettings) -> AgentLimits:
    parsed = AgentScheduleConfig.model_validate(config)
    timeout_seconds = parsed.timeout_seconds or settings.default_timeout_seconds
    return AgentLimits(
        concurrency=parsed.concurrency or settings.default_concurrency,
        timeout=timedelta(seconds=timeout_seconds),
    )
