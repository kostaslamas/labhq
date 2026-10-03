"""Discord bot credentials and placement, from `LABHQ_DISCORD_*` variables or the data directory.

`labhq onboard discord` stores what it learns as one file per field (`bot_token`, `guild_id`,
`owner_id`) in `<data_dir>/discord/`, owner-only. A variable, when set, wins over its file.
"""

from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SecretsSettingsSource,
    SettingsConfigDict,
)

from labhq.settings import Settings

CONFIG_DIRNAME = "discord"


def config_dir(data_dir: Path) -> Path:
    return data_dir / CONFIG_DIRNAME


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

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        sources = (init_settings, env_settings, dotenv_settings, file_secret_settings)
        directory = config_dir(Settings().data_dir)
        # Checked first: the source warns about a missing directory, and most installs have none.
        if not directory.is_dir():
            return sources
        return (*sources, SecretsSettingsSource(settings_cls, secrets_dir=directory, env_prefix=""))
