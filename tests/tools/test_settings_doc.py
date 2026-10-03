from enum import StrEnum
from pathlib import Path

import pytest
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from tools import settings_doc

REPO_ROOT = Path(__file__).resolve().parents[2]


class Period(StrEnum):
    MONTH = "month"


def _home() -> Path:
    return Path("/somewhere")


class ExampleSettings(BaseSettings):
    """Example knobs, read from `LABHQ_EXAMPLE_*`."""

    model_config = SettingsConfigDict(env_prefix="LABHQ_EXAMPLE_", extra="ignore")

    # Two lines of why,
    # joined into one cell.
    interval_seconds: float = 5.0
    token: SecretStr | None = None
    roles: frozenset[str] = frozenset({"manager", "ceo"})
    cadence: dict[str, int] = Field(default_factory=dict)
    home: Path = Field(default_factory=_home)
    period: Period = Period.MONTH
    enabled: bool = True
    pipe: str = Field(default="a|b", description="Described | explicitly.")


def _rows() -> dict[str, settings_doc.Row]:
    return {row.variable: row for row in settings_doc.section(ExampleSettings).rows}


def test_the_checked_in_page_matches_the_settings_classes() -> None:
    assert settings_doc.main(["--root", str(REPO_ROOT), "--check"]) == 0


def test_every_labhq_settings_class_is_found() -> None:
    names = {cls.__name__ for cls in settings_doc.settings_classes()}
    assert {"Settings", "NotifySettings", "SchedulerSettings", "DiscordSettings"} <= names
    assert all(cls.__module__.startswith("labhq") for cls in settings_doc.settings_classes())


def test_a_new_setting_without_regenerating_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    found = settings_doc.settings_classes()
    monkeypatch.setattr(settings_doc, "settings_classes", lambda: [*found, ExampleSettings])
    assert settings_doc.main(["--root", str(REPO_ROOT), "--check"]) == 1
    assert "Run `uv run python -m tools.settings_doc`" in capsys.readouterr().out


def test_writing_then_checking_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings_doc, "settings_classes", lambda: [ExampleSettings])
    (tmp_path / "docs" / "guide").mkdir(parents=True)
    assert settings_doc.main(["--root", str(tmp_path), "--check"]) == 1
    assert settings_doc.main(["--root", str(tmp_path)]) == 0
    assert settings_doc.main(["--root", str(tmp_path), "--check"]) == 0


def test_no_settings_classes_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings_doc, "settings_classes", lambda: [])
    assert settings_doc.main(["--root", str(tmp_path), "--check"]) == 1


def test_variables_carry_the_env_prefix() -> None:
    assert "LABHQ_EXAMPLE_INTERVAL_SECONDS" in _rows()


def test_the_comment_above_a_field_is_its_description() -> None:
    assert _rows()["LABHQ_EXAMPLE_INTERVAL_SECONDS"].description == (
        "Two lines of why, joined into one cell."
    )


def test_a_field_description_wins() -> None:
    assert _rows()["LABHQ_EXAMPLE_PIPE"].description == "Described | explicitly."


@pytest.mark.parametrize(
    ("variable", "default"),
    [
        ("LABHQ_EXAMPLE_INTERVAL_SECONDS", "`5.0`"),
        ("LABHQ_EXAMPLE_TOKEN", "unset"),
        # Sets are sorted, so the page does not change between runs.
        ("LABHQ_EXAMPLE_ROLES", '`["ceo", "manager"]`'),
        ("LABHQ_EXAMPLE_CADENCE", "`{}`"),
        # A machine-dependent factory is never evaluated into the page.
        ("LABHQ_EXAMPLE_HOME", "*computed*"),
        ("LABHQ_EXAMPLE_PERIOD", "`month`"),
        ("LABHQ_EXAMPLE_ENABLED", "`true`"),
    ],
)
def test_defaults_render_the_same_on_every_machine(variable: str, default: str) -> None:
    assert _rows()[variable].default == default


def test_types_are_readable() -> None:
    rows = _rows()
    assert rows["LABHQ_EXAMPLE_TOKEN"].type == "SecretStr | None"
    assert rows["LABHQ_EXAMPLE_HOME"].type == "Path"
    assert rows["LABHQ_EXAMPLE_CADENCE"].type == "dict[str, int]"


def test_pipes_are_escaped_in_the_table() -> None:
    page = settings_doc.render([ExampleSettings])
    assert "| `LABHQ_EXAMPLE_PIPE` | `str` | `a\\|b` | Described \\| explicitly. |" in page
    assert "Example knobs, read from `LABHQ_EXAMPLE_*`." in page
