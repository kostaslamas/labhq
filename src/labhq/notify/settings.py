"""Notifier choice, credentials and retry policy, read from `LABHQ_NOTIFY_*` variables."""

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class NotifySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LABHQ_NOTIFY_", extra="ignore")

    # A key of `labhq.notify.registry.notifiers`; ntfy needs no account.
    kind: str = "ntfy"
    ntfy_server: str = "https://ntfy.sh"
    # Unset: a random topic is generated once and kept in the data directory.
    ntfy_topic: str | None = None
    ntfy_priority: str = "high"
    # SecretStr keeps the token out of reprs and tracebacks of the settings object.
    telegram_token: SecretStr | None = None
    telegram_chat_id: str | None = None

    max_attempts: int = Field(default=5, gt=0)
    backoff_base_seconds: int = Field(default=30, gt=0)
    backoff_max_seconds: int = Field(default=3600, gt=0)
    # A claimed row is invisible to other dispatchers this long; a crashed send retries after it.
    claim_lease_seconds: int = Field(default=120, gt=0)


@lru_cache(maxsize=1)
def get_notify_settings() -> NotifySettings:
    return NotifySettings()
