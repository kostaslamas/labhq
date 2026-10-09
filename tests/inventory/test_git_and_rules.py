"""Git facts (and `gh` only when logged in), and the proposed action as a rule table."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from labhq.inventory.git import git_facts, open_pull_request
from labhq.inventory.model import Action, GitFacts, SessionInfo, SessionState
from labhq.inventory.propose import propose
from labhq.inventory.settings import InventorySettings
from tests.inventory.conftest import make_repo

NOW = datetime(2026, 6, 1, tzinfo=UTC)


def gh(logged_in: bool, pr: dict[str, object] | None):
    def command(argv, cwd, timeout):
        if tuple(argv[:3]) == ("gh", "auth", "status"):
            return "ok" if logged_in else None
        return json.dumps(pr) if pr is not None else None

    return command


def test_git_facts_report_branch_dirty_files_and_the_last_commit(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "party", "add the lobby")
    (repo / "a.txt").write_text("changed\n", encoding="utf-8")
    (repo / "new.txt").write_text("new\n", encoding="utf-8")

    facts = git_facts(repo, use_gh=False, timeout=5)

    assert (facts.branch, facts.dirty_files) == ("main", 2)
    assert facts.last_commit_subject == "add the lobby"
    assert facts.last_commit_at is not None and facts.open_pr is None


def test_the_open_pull_request_is_asked_of_gh_only_when_it_is_logged_in(tmp_path: Path) -> None:
    pr = {"number": 7, "title": "Lobby", "state": "OPEN", "url": "u"}

    assert open_pull_request(tmp_path, "main", timeout=1, command=gh(True, pr)) == "#7 Lobby"
    assert open_pull_request(tmp_path, "main", timeout=1, command=gh(False, pr)) is None
    assert (
        open_pull_request(tmp_path, "main", timeout=1, command=gh(True, {**pr, "state": "MERGED"}))
        is None
    )
    assert open_pull_request(tmp_path, "main", timeout=1, command=gh(True, None)) is None
    assert open_pull_request(tmp_path, "HEAD", timeout=1, command=gh(True, pr)) is None


def session(
    idle: timedelta, *, pid: int | None = None, state: SessionState = SessionState.IDLE
) -> SessionInfo:
    return SessionInfo(
        "claude-code", "s", Path("/w"), state, NOW - idle, idle.total_seconds(), pid=pid
    )


@pytest.mark.parametrize(
    ("info", "git", "expected"),
    [
        (
            session(timedelta(hours=1), pid=1, state=SessionState.WAITING),
            GitFacts(),
            Action.CONTINUE,
        ),
        (session(timedelta(hours=20), pid=1), GitFacts(), Action.CLOSE),
        (session(timedelta(hours=1), pid=1), GitFacts(), Action.CONTINUE),
        (session(timedelta(days=3)), GitFacts(dirty_files=2), Action.CONTINUE),
        (session(timedelta(days=3)), GitFacts(), Action.CONTINUE),
        (session(timedelta(days=60)), GitFacts(dirty_files=2), Action.HISTORY),
    ],
)
def test_the_proposed_action_follows_the_rule_table(
    info: SessionInfo, git: GitFacts, expected: Action
) -> None:
    assert propose(info, git, NOW, InventorySettings()).action is expected


def test_the_thresholds_are_settings() -> None:
    quick = InventorySettings(idle_close_hours=0.5)

    assert (
        propose(session(timedelta(hours=1), pid=1), GitFacts(), NOW, quick).action is Action.CLOSE
    )
    assert replace(session(timedelta(days=1)), idle_seconds=None).idle_seconds is None
