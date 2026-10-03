"""API settings, read from `LABHQ_API_*` environment variables."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_UI_DIR = Path("web/dist")


class ApiSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LABHQ_API_", extra="ignore")

    # The built desktop UI. Served at `/` only when it exists; the API works without it.
    ui_dir: Path = DEFAULT_UI_DIR
    default_page_size: int = Field(default=50, gt=0)
    max_page_size: int = Field(default=200, gt=0)


def get_api_settings() -> ApiSettings:
    # Not cached: tests change the environment between apps.
    return ApiSettings()
