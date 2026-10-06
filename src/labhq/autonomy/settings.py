"""Autonomy and heartbeat defaults, read from `LABHQ_AUTONOMY` and `LABHQ_CEO_HEARTBEAT_SECONDS`."""

from enum import StrEnum
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Autonomy(StrEnum):
    ON = "on"
    PAUSED = "paused"


class AutonomySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LABHQ_", extra="ignore")

    # The start-up value of the global switch. The owner can flip it at runtime from the API;
    # that choice is stored in the database and wins over this one.
    autonomy: Autonomy = Autonomy.ON
    # Seconds between two heartbeat wakeups of the global CEO. 0 turns the heartbeat off.
    ceo_heartbeat_seconds: int = Field(default=3600, ge=0)


@lru_cache(maxsize=1)
def get_autonomy_settings() -> AutonomySettings:
    return AutonomySettings()
