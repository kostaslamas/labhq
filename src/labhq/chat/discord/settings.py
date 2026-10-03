"""Discord bot credentials and placement, read from `LABHQ_DISCORD_*` variables."""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class DiscordSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LABHQ_DISCORD_", extra="ignore")

    # A Discord credential. SecretStr keeps it out of reprs and tracebacks of this object.
    bot_token: SecretStr | None = None
    guild_id: str | None = None
    # Only this user's messages are read back; everyone else in the server is ignored.
    owner_id: str | None = None
    category_name: str = "labhq"
    api_base: str = "https://discord.com/api/v10"
    max_attempts: int = Field(default=5, gt=0)
    reconnect_seconds: float = Field(default=5.0, ge=0)
