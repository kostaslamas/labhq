"""Onboarding knobs, read from `LABHQ_ONBOARD_*` variables."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class OnboardSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LABHQ_ONBOARD_", extra="ignore")

    host: str = "127.0.0.1"
    port: int = Field(default=8787, gt=0, lt=65536)
    # A fresh quick-tunnel hostname can take a few seconds to resolve after cloudflared prints it.
    verify_attempts: int = Field(default=6, gt=0)
    verify_delay_seconds: float = Field(default=2.0, ge=0)
    server_start_timeout_seconds: float = Field(default=10.0, gt=0)
    login_check_timeout_seconds: float = Field(default=15.0, gt=0)
    http_timeout_seconds: float = Field(default=10.0, gt=0)
