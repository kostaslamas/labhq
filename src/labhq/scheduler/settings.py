"""Scheduler limits, read from `LABHQ_SCHEDULER_*`, and their per-agent overrides."""

from functools import lru_cache
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SchedulerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LABHQ_SCHEDULER_", extra="ignore")

    # Plan §7 rule 2: a low default, one run at a time per agent.
    default_concurrency: int = Field(default=1, gt=0)
    default_timeout_seconds: int = Field(default=3600, gt=0)
    # A run silent for this long has lost its owner. The scheduler beats live runs on
    # every tick, so the limit only has to outlast a few ticks, not a long tool call.
    heartbeat_limit_seconds: int = Field(default=300, gt=0)
    # Time a timed-out run gets to honour its interrupt before it is abandoned.
    interrupt_grace_seconds: int = Field(default=30, gt=0)
    tick_seconds: float = Field(default=5.0, gt=0)
    # An agent that ends a turn without a handoff gets another turn. 0 keeps it going until
    # the task is resolved (the owner's choice); its budget and the plan-usage cap still stop
    # it. A positive limit marks the task blocked and sends it to the reviewer instead.
    max_unreported_runs: int = Field(default=0, ge=0)
    # Every this many silent turns the reviewer (the parent task's assignee) is woken to look
    # at the stuck task while it keeps going. 0 never alerts.
    stall_alert_runs: int = Field(default=3, ge=0)
    # Runs active at once across all agents. Unset, it follows the machine: about one per
    # 1.5 GB of RAM, between 1 and 8 (`labhq.scheduler.memory`).
    max_running: int | None = Field(default=None, gt=0)
    # Below this share of free RAM no run starts; wakeups wait. 0 turns the check off.
    min_free_memory_percent: float = Field(default=15.0, ge=0, le=100)


class AgentLimits(BaseModel):
    """The keys of `agents.config` the scheduler reads. Other keys belong to adapters."""

    model_config = ConfigDict(extra="ignore")

    max_concurrency: int = Field(gt=0)
    timeout_seconds: int = Field(gt=0)

    @classmethod
    def from_config(cls, config: dict[str, Any], settings: SchedulerSettings) -> "AgentLimits":
        return cls.model_validate(
            {
                "max_concurrency": settings.default_concurrency,
                "timeout_seconds": settings.default_timeout_seconds,
                **config,
            }
        )


@lru_cache(maxsize=1)
def get_scheduler_settings() -> SchedulerSettings:
    return SchedulerSettings()
