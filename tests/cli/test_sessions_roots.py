"""`labhq sessions roots`: list, add and remove, validated, kept in the database."""

from pathlib import Path

import pytest

from tests.cli.conftest import Cli
from tests.inventory import stores_fixture as fx
from tests.inventory.conftest import make_repo


@pytest.fixture(autouse=True)
def quiet_machine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr("psutil.process_iter", lambda *args, **kwargs: iter(()))
    for name in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "CLAUDE_CONFIG_DIR", "CODEX_HOME"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path / "home"


def test_the_list_starts_machine_wide_then_follows_add_and_remove(cli: Cli, tmp_path: Path) -> None:
    cli.ok("init")
    projects = tmp_path / "projects"
    projects.mkdir()

    assert "machine-wide: no scope set" in cli.ok("sessions", "roots")
    assert "added" in cli.ok("sessions", "roots", "add", str(projects))
    assert cli.ok("sessions", "roots", "list").strip() == str(projects.resolve())
    # The setting is a row in labhq's own table, not a dotfile.
    (row,) = cli.rows("SELECT value FROM program_state WHERE key = 'inventory_roots'")
    assert str(projects.resolve()) in row["value"]

    assert "removed" in cli.ok("sessions", "roots", "remove", str(projects))
    assert "machine-wide" in cli.ok("sessions", "roots", "list")


def test_add_refuses_the_filesystem_root_and_a_missing_folder(cli: Cli, tmp_path: Path) -> None:
    cli.ok("init")

    root = cli("sessions", "roots", "add", "/")
    missing = cli("sessions", "roots", "add", str(tmp_path / "nope"))

    assert root.exit_code == 1 and "root of a filesystem" in root.stderr
    assert missing.exit_code == 1 and "does not exist" in missing.stderr
    assert cli.rows("SELECT key FROM program_state WHERE key = 'inventory_roots'") == []


def test_removing_a_folder_that_is_not_a_root_fails(cli: Cli, tmp_path: Path) -> None:
    cli.ok("init")

    result = cli("sessions", "roots", "remove", str(tmp_path))

    assert result.exit_code == 1 and "not one of the scan roots" in result.stderr


def test_a_scan_honours_the_stored_roots_and_reports_what_it_left_out(
    cli: Cli, quiet_machine: Path, tmp_path: Path
) -> None:
    cli.ok("init")
    mine, other = make_repo(tmp_path / "dev" / "mine"), make_repo(tmp_path / "work" / "other")
    fx.claude(quiet_machine, mine)
    fx.codex(quiet_machine, other)
    cli.ok("sessions", "roots", "add", str(tmp_path / "dev"))

    output = cli.ok("sessions", "scan", "--no-report")

    assert "Project mine" in output and "Project other" not in output
    assert "1 session left out" in output
    assert str(other) not in output


def test_the_home_folder_is_added_with_a_warning(
    cli: Cli, quiet_machine: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli.ok("init")
    quiet_machine.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(quiet_machine))

    assert "warning: this is your home folder" in cli.ok(
        "sessions", "roots", "add", str(quiet_machine)
    )
