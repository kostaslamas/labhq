import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
import typer
from typer.core import TyperGroup

from labhq.cli import app
from tests.cli.conftest import Cli, plain


def command_paths(group: TyperGroup, prefix: tuple[str, ...] = ()) -> Iterator[tuple[str, ...]]:
    for name, command in group.commands.items():
        path = (*prefix, name)
        yield path
        if isinstance(command, TyperGroup):
            yield from command_paths(command, path)


ROOT = typer.main.get_group(app)
assert isinstance(ROOT, TyperGroup)
ALL_COMMANDS = sorted(command_paths(ROOT))
LEAF_COMMANDS = [
    path
    for path in ALL_COMMANDS
    if not any(other[: len(path)] == path and other != path for other in ALL_COMMANDS)
]

# One failing invocation per leaf command, on a fresh data directory with no database
# unless `init` is listed first. A new command without a row here fails the coverage test.
FAILURES: dict[tuple[str, ...], tuple[tuple[str, ...], ...]] = {
    ("init",): (("init",),),
    ("project", "add"): (("init",), ("project", "add", "p", "--repo", "{not_a_repo}")),
    ("agent", "add"): (
        ("init",),
        ("agent", "add", "--project", "nope", "--role", "worker", "--title", "W"),
    ),
    ("agent", "approve"): (("init",), ("agent", "approve", "42")),
    ("task", "add"): (("init",), ("task", "add", "--project", "nope", "--title", "T")),
    ("run",): (("run",),),
    ("approvals", "list"): (("approvals", "list"),),
    ("approvals", "approve"): (("init",), ("approvals", "approve", "42")),
    ("approvals", "reject"): (("init",), ("approvals", "reject", "42")),
    ("health",): (("health",),),
}


def test_every_command_has_a_failure_case() -> None:
    assert sorted(FAILURES) == LEAF_COMMANDS


@pytest.mark.parametrize("path", ALL_COMMANDS, ids=" ".join)
def test_every_command_has_help_text(cli: Cli, path: tuple[str, ...]) -> None:
    result = cli(*path, "--help")
    assert result.exit_code == 0
    lines = [line.strip() for line in plain(result.stdout).splitlines() if line.strip()]
    usage, description = lines[0], lines[1]
    assert usage.startswith(f"Usage: labhq {' '.join(path)}")
    # Rich draws option panels in boxes; the line after the usage must be prose.
    assert description[0].isalpha() and len(description.split()) >= 3, description


@pytest.mark.parametrize("path", sorted(FAILURES), ids=" ".join)
def test_every_command_exits_non_zero_on_failure(
    cli: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path: tuple[str, ...]
) -> None:
    not_a_repo = tmp_path / "plain-directory"
    not_a_repo.mkdir()
    if path == ("init",):
        # A data directory that cannot be created: a file sits where it should be.
        blocked = tmp_path / "blocked"
        blocked.write_text("", encoding="utf-8")
        monkeypatch.setenv("LABHQ_DATA_DIR", str(blocked / "data"))
    *setup, failing = FAILURES[path]
    for step in setup:
        cli.ok(*step)

    result = cli(*(arg.format(not_a_repo=not_a_repo) for arg in failing))

    assert result.exit_code != 0
    assert result.stderr.startswith("error: ")


def test_commands_before_init_point_to_init(cli: Cli) -> None:
    result = cli("approvals", "list")
    assert result.exit_code == 1
    assert "labhq init" in result.stderr


def test_a_project_runs_by_hand_from_init_to_a_pending_push(cli: Cli, repo: Path) -> None:
    cli.ok("init")
    cli.ok("project", "add", "site", "--repo", str(repo), "--budget-usd", "5")
    added = cli.ok("agent", "add", "--project", "site", "--role", "worker", "--title", "Worker")
    assert "pending_approval" in added
    cli.ok("task", "add", "--project", "site", "--title", "Fix the footer", "--assignee", "1")

    # A new agent waits for approval (plan §5, rule 4): nothing starts.
    assert "no runs finished" in cli.ok("run")
    cli.ok("agent", "approve", "1")
    output = cli.ok("run")

    assert "run 1: succeeded" in output
    assert "requested approval 1: push [heavy] pending" in output
    assert "approval 1: push" in cli.ok("approvals", "list")
    [project] = cli.rows("SELECT budget_micros FROM projects")
    assert project["budget_micros"] == 5_000_000


def test_run_exits_non_zero_when_a_run_fails(cli: Cli, repo: Path) -> None:
    cli.ok("init")
    cli.ok("project", "add", "gone", "--repo", str(repo))
    cli.ok("agent", "add", "--project", "gone", "--role", "worker", "--title", "Worker")
    cli.ok("agent", "approve", "1")
    cli.ok("task", "add", "--project", "gone", "--title", "Lost", "--assignee", "1")
    # The repository disappears, so the task's worktree cannot be made.
    shutil.rmtree(repo)

    result = cli("run")

    assert result.exit_code == 1
    assert "run 1: failed" in plain(result.stdout)
    assert cli.rows("SELECT checkout_run_id FROM tasks")[0]["checkout_run_id"] is None


def test_an_assignee_from_another_project_is_refused(cli: Cli, repo: Path) -> None:
    cli.ok("init")
    cli.ok("project", "add", "one", "--repo", str(repo))
    cli.ok("project", "add", "two", "--repo", str(repo))
    cli.ok("agent", "add", "--project", "one", "--role", "worker", "--title", "Worker")

    result = cli("task", "add", "--project", "two", "--title", "T", "--assignee", "1")

    assert result.exit_code == 1
    assert "does not belong to project" in result.stderr


def test_a_budget_must_be_an_amount(cli: Cli, repo: Path) -> None:
    cli.ok("init")
    result = cli("project", "add", "p", "--repo", str(repo), "--budget-usd", "lots")
    assert result.exit_code == 1
    assert "budget must be" in result.stderr


def test_health_collects_a_sample_of_this_machine(cli: Cli) -> None:
    cli.ok("init")
    assert "no samples yet" in cli.ok("health")

    output = cli.ok("health", "--collect")

    assert "memory.percent" in output
    assert "0 open incident(s)" in output
