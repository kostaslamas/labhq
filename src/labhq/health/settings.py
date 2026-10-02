"""Health configuration, read from `LABHQ_HEALTH_*` environment variables."""

import socket

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class HealthSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LABHQ_HEALTH_", extra="ignore")

    # Plan §2.2: the collector samples "every few minutes".
    sample_interval_seconds: float = Field(default=300.0, gt=0)
    # Names the `hosts` row the collector creates on first run.
    local_host_name: str = Field(default_factory=socket.gethostname, min_length=1)
