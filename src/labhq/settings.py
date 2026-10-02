"""Process-wide configuration, read from `LABHQ_*` environment variables."""

from functools import lru_cache
from pathlib import Path

from platformdirs import user_data_path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DATABASE_FILENAME = "labhq.sqlite3"


def _default_data_dir() -> Path:
    return user_data_path("labhq", appauthor=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LABHQ_", extra="ignore")

    data_dir: Path = Field(default_factory=_default_data_dir)
    # Overrides the SQLite file under `data_dir`; tests and CI point it at a scratch database.
    database_url: str | None = None
    # The SDK wheel bundles its own Claude Code build; runs pin the installed one instead
    # (spikes/agent_sdk/RESULTS.md).
    cli_path: Path | None = None

    @property
    def resolved_database_url(self) -> str:
        if self.database_url is not None:
            return self.database_url
        return sqlite_url(self.data_dir / DATABASE_FILENAME)


def sqlite_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
