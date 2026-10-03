"""How often each background duty of the always-on program runs, from `LABHQ_PROGRAM_*`."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProgramSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LABHQ_PROGRAM_", extra="ignore")

    # Matches the scheduler's own tick: a run is never noticed later than it is policed.
    scheduler_interval_seconds: float = Field(default=5.0, gt=0)
    # A pending notification waits at most this long; the outbox applies its own backoff.
    notify_interval_seconds: float = Field(default=15.0, gt=0)
    # Status files change while a run is live, so a question surfaces before the run ends.
    status_interval_seconds: float = Field(default=30.0, gt=0)
    # Time the server gets to stop before it is cancelled on shutdown.
    shutdown_grace_seconds: float = Field(default=10.0, gt=0)


@lru_cache(maxsize=1)
def get_program_settings() -> ProgramSettings:
    return ProgramSettings()
