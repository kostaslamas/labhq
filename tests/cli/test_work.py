"""Adding projects, agents and tasks, and one scheduler pass over them."""

import shutil
from pathlib import Path

import pytest

from labhq.worktrees.git import run_git
from tests.cli.conftest import Cli


def set_up(cli: Cli, repo: Path) -> None:
    cli.ok("init")
    cli.ok("project", "add", "site", "--repo", str(repo), "--budget-usd", "2.5")
    cli.ok("agent", "add", "-p", "site", "--role", "manager", "--adapter", "fake")
    cli.ok(
        "agent", "add", "-p", "site", "--role", "worker", "--adapter", "fake", "--reports-to", "1"
    )


def test_project_agent_and_task_rows(cli: Cli, repo: Path) -> None:
    set_up(cli, repo)
    output = cli.ok("task", "add", "-p", "site", "--title", "Fix the footer", "--assignee", "2")

    assert cli.rows("SELECT name, repo_path, budget_micros FROM projects") == [
        ("site", str(repo.resolve()), 2_500_000)
    ]
    assert cli.rows("SELECT role, title, reports_to, status FROM agents ORDER BY id") == [
        ("manager", "Manager", None, "active"),
        ("worker", "Worker", 1, "active"),
    ]
    assert cli.rows("SELECT title, assignee_id FROM tasks") == [("Fix the footer", 2)]
    assert cli.rows("SELECT agent_id, task_id, source, status FROM wakeup_requests") == [
        (2, 1, "assignment", "pending")
    ]
    assert "wakeup 1 created" in output


def test_run_works_the_task_in_its_worktree(cli: Cli, repo: Path) -> None:
    set_up(cli, repo)
    cli.ok("task", "add", "-p", "site", "--title", "Fix the footer", "--assignee", "2")

    output = cli.ok("run")

    assert "run 1 started" in output and "run 1 finished" in output
    assert cli.rows("SELECT status FROM runs") == [("succeeded",)]
    assert cli.rows("SELECT run_id, cost_micros FROM cost_events") == [(1, 12_500)]
    assert cli.rows("SELECT checkout_run_id FROM tasks") == [(None,)]
    assert "labhq/task-1-fix-the-footer" in run_git("branch", "--list", cwd=repo)
    # The fake made no commit, so there is nothing to ask to push.
    assert cli.rows("SELECT id FROM approvals") == []


def test_a_run_without_rtk_records_the_warning(
    cli: Cli, repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_up(cli, repo)
    cli.ok("task", "add", "-p", "site", "--title", "t", "--assignee", "2")
    # A PATH with git and nothing else, so no rtk installed on this machine is found.
    only_git = tmp_path / "bin"
    only_git.mkdir()
    git = shutil.which("git")
    assert git is not None
    (only_git / "git").symlink_to(git)
    monkeypatch.setenv("PATH", str(only_git))

    cli.ok("run")

    assert cli.rows("SELECT seq, kind, json_extract(payload, '$.code') FROM run_events")[0] == (
        0,
        "warning",
        "rtk_missing",
    )


def test_a_second_run_with_nothing_pending_starts_nothing(cli: Cli, repo: Path) -> None:
    set_up(cli, repo)
    cli.ok("task", "add", "-p", "site", "--title", "t", "--assignee", "2")
    cli.ok("run")

    output = cli.ok("run")

    assert "started" not in output
    assert cli.rows("SELECT count(*) FROM runs") == [(1,)]


def test_an_agent_cannot_report_to_another_project(cli: Cli, repo: Path) -> None:
    set_up(cli, repo)
    cli.ok("project", "add", "other", "--repo", str(repo))

    result = cli("agent", "add", "-p", "other", "--role", "worker", "--adapter", "fake",
                 "--reports-to", "1")  # fmt: skip

    assert result.exit_code == 1
    assert "not in project 'other'" in result.stderr


def test_a_task_cannot_go_to_another_projects_agent(cli: Cli, repo: Path) -> None:
    set_up(cli, repo)
    cli.ok("project", "add", "other", "--repo", str(repo))

    result = cli("task", "add", "-p", "other", "--title", "t", "--assignee", "2")

    assert result.exit_code == 1
    assert cli.rows("SELECT count(*) FROM tasks") == [(0,)]


def test_bad_input_is_reported_not_raised(cli: Cli, repo: Path) -> None:
    set_up(cli, repo)
    cases = [
        ("project", "add", "x", "--repo", str(repo), "--budget-usd", "lots"),
        ("project", "add", "site", "--repo", str(repo)),
        ("agent", "add", "-p", "site", "--role", "w", "--adapter", "nope"),
        ("agent", "add", "-p", "site", "--role", "w", "--adapter", "fake", "--config", "[1]"),
        ("agent", "add", "-p", "site", "--role", "w", "--adapter", "fake", "--config", "{"),
    ]
    for args in cases:
        result = cli(*args)
        assert result.exit_code == 1, (args, result.output)
        assert "error:" in result.stderr, args
