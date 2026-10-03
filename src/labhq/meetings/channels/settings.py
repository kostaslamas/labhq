"""Meeting channel settings, read from `LABHQ_CHANNELS_*` environment variables."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ChannelSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LABHQ_CHANNELS_", extra="ignore")

    # Which configured chat adapter mirrors meetings; unset takes the first configured one.
    adapter: str | None = None
    # Plan §2.2: incidents reach `#infra`.
    infra_channel: str = Field(default="infra", min_length=1)
    # How often a running chat pass drains the outbox: a post reaches its thread this late.
    drain_interval_seconds: float = Field(default=2.0, gt=0)
    # Backoff after a failed post: doubles from the base up to the cap, then stays there.
    retry_base_seconds: float = Field(default=5.0, gt=0)
    retry_max_seconds: float = Field(default=300.0, gt=0)
    # Posts sent per pass, so a long backlog does not hold one pass for minutes.
    batch_size: int = Field(default=100, gt=0)
    # Incidents opened or resolved this long ago are still posted after a restart; older ones
    # are history, not news.
    incident_lookback_seconds: float = Field(default=86400.0, gt=0)
    # An agent without `config["persona"]["avatar_url"]` gets this, with `{seed}` filled from
    # its id. Empty means no avatar: the chat service shows its default.
    avatar_url_template: str = "https://api.dicebear.com/9.x/bottts/png?seed={seed}"
    system_name: str = Field(default="labhq", min_length=1)


@lru_cache(maxsize=1)
def get_channel_settings() -> ChannelSettings:
    return ChannelSettings()
