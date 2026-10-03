import re
import tomllib
from pathlib import Path

from typer.testing import CliRunner

from labhq import __version__
from labhq.cli import app

# CI sets FORCE_COLOR, so rich styles the help text and splits option names with escapes.
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def test_version_prints_the_package_version() -> None:
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == f"labhq {__version__}"
    # The source of truth is pyproject.toml, so a release bump never edits this test.
    pyproject = Path(__file__).parents[2] / "pyproject.toml"
    assert __version__ == tomllib.loads(pyproject.read_text())["project"]["version"]


def test_help_lists_the_version_option() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "--version" in _ANSI.sub("", result.stdout)
