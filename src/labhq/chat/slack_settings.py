"""Slack app credentials and placement, read from `LABHQ_SLACK_*` variables."""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class SlackSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LABHQ_SLACK_", extra="ignore")

    # Slack credentials. SecretStr keeps them out of reprs and tracebacks of this object.
    # The bot token (xoxb-) calls the Web API; the app-level token (xapp-) opens Socket Mode.
    bot_token: SecretStr | None = None
    app_token: SecretStr | None = None
    # Only this member's messages are read back; everyone else in the workspace is ignored.
    owner_id: str | None = None
    channel_prefix: str = "labhq-"
    api_base: str = "https://slack.com/api"
    max_attempts: int = Field(default=5, gt=0)
    reconnect_seconds: float = Field(default=5.0, ge=0)

    def configured(self) -> bool:
        return self.bot_token is not None and self.app_token is not None
