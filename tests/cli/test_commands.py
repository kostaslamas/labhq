"""Every command explains itself with `--help` and fails with a non-zero exit status."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import typer

from labhq.cli import app
from tests.cli.conftest import ANSI, Cli


# Typer vendors its own click, so groups are recognised by their `commands` mapping.
def subcommands(command: Any) -> dict[str, Any]:
    return dict(sorted(getattr(command, "commands", {}).items()))


def leaf_commands(command: Any, path: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    children = subcommands(command)
    if not children:
        return [path]
    return [leaf for name, sub in children.items() for leaf in leaf_commands(sub, (*path, name))]


def all_commands(command: Any, path: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    paths = [path]
    for name, sub in subcommands(command).items():
        paths.extend(all_commands(sub, (*path, name)))
    return paths


ROOT = typer.main.get_command(app)
LEAVES = leaf_commands(ROOT)


@dataclass(frozen=True)
class Failure:
    args: tuple[str, ...]
    initialised: bool = True
    env: dict[str, str] = field(default_factory=dict)


# One failing invocation per command; `test_every_command_has_a_failure_case` keeps the
# table complete when a command is added.
FAILURES: dict[tuple[str, ...], Failure] = {
    ("init",): Failure(
        ("init",),
        initialised=False,
        env={"LABHQ_DATABASE_URL": "sqlite+aiosqlite:////nonexistent/dir/labhq.sqlite3"},
    ),
    ("project", "add"): Failure(("project", "add", "p", "--repo", "/nonexistent/repo")),
    ("agent", "add"): Failure(
        ("agent", "add", "--project", "nope", "--role", "worker", "--adapter", "fake")
    ),
    ("task", "add"): Failure(("task", "add", "--project", "nope", "--title", "t")),
    ("run",): Failure(("run",), initialised=False),
    ("approvals", "list"): Failure(("approvals", "list", "--status", "bogus")),
    ("approvals", "approve"): Failure(("approvals", "approve", "99")),
    ("approvals", "reject"): Failure(("approvals", "reject", "99")),
    ("health",): Failure(("health",), initialised=False),
    ("demo",): Failure(("demo", "--adapter", "nope")),
}


def test_the_command_tree_is_complete() -> None:
    assert set(LEAVES) == {
        ("init",),
        ("project", "add"),
        ("agent", "add"),
        ("task", "add"),
        ("run",),
        ("approvals", "list"),
        ("approvals", "approve"),
        ("approvals", "reject"),
        ("health",),
        ("demo",),
    }


@pytest.mark.parametrize("path", all_commands(ROOT), ids=lambda p: " ".join(p) or "labhq")
def test_every_command_has_help(cli: Cli, path: tuple[str, ...]) -> None:
    result = cli(*path, "--help")
    assert result.exit_code == 0, result.output
    text = ANSI.sub("", result.stdout)
    assert "Usage:" in text
    command = ROOT
    for name in path:
        command = subcommands(command)[name]
    assert command.help and command.help.strip()
    assert command.help.strip().splitlines()[0] in text


def test_every_command_has_a_failure_case() -> None:
    assert set(FAILURES) == set(LEAVES)


@pytest.mark.parametrize("path", LEAVES, ids=" ".join)
def test_every_command_exits_non_zero_on_failure(
    cli: Cli, monkeypatch: pytest.MonkeyPatch, path: tuple[str, ...]
) -> None:
    failure = FAILURES[path]
    if failure.initialised:
        cli.ok("init")
    for name, value in failure.env.items():
        monkeypatch.setenv(name, value)

    result = cli(*failure.args)

    assert result.exit_code != 0, result.output
    assert "error:" in result.stderr
    # An expected failure is reported, not raised as a traceback.
    assert isinstance(result.exception, SystemExit)


def test_an_unknown_command_exits_non_zero(cli: Cli) -> None:
    assert cli("no-such-command").exit_code != 0


def test_a_missing_required_option_exits_non_zero(cli: Cli) -> None:
    assert cli("project", "add", "p").exit_code != 0


def test_init_is_repeatable(cli: Cli) -> None:
    cli.ok("init")
    output = cli.ok("init")
    assert "database ready" in output
    assert (cli.data_dir / "labhq.sqlite3").is_file()


def test_a_command_before_init_names_the_fix(cli: Cli, tmp_path: Path) -> None:
    cli.data_dir.mkdir()
    result = cli("approvals", "list")
    assert result.exit_code == 1
    assert "labhq init" in result.stderr
