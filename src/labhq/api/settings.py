"""API settings, read from `LABHQ_API_*` environment variables."""

from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# The wheel carries the built UI here (tools/build_web.py); a checkout builds it in web/dist.
PACKAGED_UI_DIR = Path(__file__).resolve().parent.parent / "web"
SOURCE_UI_DIR = Path("web/dist")
# Written into the wheel's dist-info by a `LABHQ_SKIP_WEB_BUILD=1` build.
UI_ABSENT_MARKER = "extra_metadata/web-ui-absent"


def default_ui_dir() -> Path:
    return PACKAGED_UI_DIR if PACKAGED_UI_DIR.is_dir() else SOURCE_UI_DIR


class ApiSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LABHQ_API_", extra="ignore")

    # The built desktop UI. Served at `/` only when it exists; the API works without it.
    ui_dir: Path = Field(default_factory=default_ui_dir)
    default_page_size: int = Field(default=50, gt=0)
    max_page_size: int = Field(default=200, gt=0)


def get_api_settings() -> ApiSettings:
    # Not cached: tests change the environment between apps.
    return ApiSettings()


def built_without_ui() -> bool:
    try:
        return distribution("labhq").read_text(UI_ABSENT_MARKER) is not None
    except PackageNotFoundError:
        return False


def ui_absent_reason(settings: ApiSettings) -> str | None:
    """Why `/` serves no UI, for `labhq serve` to say; None when the UI is there."""
    if settings.ui_dir.is_dir():
        return None
    if built_without_ui():
        return (
            "the web UI is absent: this labhq was built with LABHQ_SKIP_WEB_BUILD=1; "
            "the API and MCP work without it"
        )
    return (
        f"the web UI is absent: no built UI at {settings.ui_dir}; "
        "run `npm run build` in web/ or set LABHQ_API_UI_DIR"
    )
