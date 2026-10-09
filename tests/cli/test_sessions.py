"""`labhq sessions`: scan files CEO reports; analyse only asks for approval."""

from pathlib import Path

import pytest

from tests.cli.conftest import Cli
from tests.inventory import stores_fixture as fx
from tests.inventory.conftest import make_repo


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # The developer's own agents must not show up in a scan under test.
    monkeypatch.setattr("psutil.process_iter", lambda *args, **kwargs: iter(()))
    # `isolated_git` (autouse for the CLI tests) has already made and exported the home.
    for name in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "CLAUDE_CONFIG_DIR", "CODEX_HOME"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path / "home"


def test_scan_prints_each_project_and_files_a_report_per_project(
    cli: Cli, home: Path, tmp_path: Path
) -> None:
    cli.ok("init")
    fx.claude(home, make_repo(tmp_path / "party"))

    output = cli.ok("sessions", "scan")

    assert "Project party" in output and "claude-code" in output
    assert len(cli.rows("SELECT id FROM ceo_reports")) == 1


def test_scan_can_skip_the_ceo_report(cli: Cli, home: Path, tmp_path: Path) -> None:
    cli.ok("init")
    fx.claude(home, make_repo(tmp_path / "party"))

    cli.ok("sessions", "scan", "--no-report")

    assert cli.rows("SELECT id FROM ceo_reports") == []


def test_analysing_an_unknown_project_is_one_line_and_starts_nothing(cli: Cli, home: Path) -> None:
    cli.ok("init")

    result = cli("sessions", "analyse", "nothing")

    assert result.exit_code == 1 and "no project named" in result.stderr
    assert cli.rows("SELECT id FROM approvals") == []
    assert cli.rows("SELECT id FROM runs") == []
