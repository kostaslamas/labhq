"""Live-update settings, read from `LABHQ_LIVE_*` environment variables.

The poll interval is a program setting (`live_interval_seconds`) because the loop that polls
belongs to the program; what the socket does is configured here.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LiveSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LABHQ_LIVE_", extra="ignore")

    # Below the 100 s idle timeout of Cloudflare and the 60 s default of nginx and Caddy, so an
    # idle socket is never cut by a proxy; the client treats twice this silence as a dead link.
    heartbeat_seconds: float = Field(default=20.0, gt=0)


def get_live_settings() -> LiveSettings:
    # Not cached: tests change the environment between apps.
    return LiveSettings()
