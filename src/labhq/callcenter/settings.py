"""Call timing, read from `LABHQ_CALLCENTER_*` environment variables."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class CallCenterSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LABHQ_CALLCENTER_", extra="ignore")

    # A call with no activity for this long is treated as hung up.
    call_window_seconds: int = Field(default=300, gt=0)
    # A request nobody answered within this time becomes `expired` instead of waiting forever.
    ticket_expiry_seconds: int = Field(default=3600, gt=0)


@lru_cache(maxsize=1)
def get_callcenter_settings() -> CallCenterSettings:
    return CallCenterSettings()
