from typer.testing import CliRunner

from labhq import __version__
from labhq.cli import app


def test_version_prints_the_package_version() -> None:
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == f"labhq {__version__}"
    assert __version__ == "0.1.0.dev0"


def test_help_lists_the_version_option() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "--version" in result.stdout
