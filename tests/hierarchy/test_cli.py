"""`labhq org`: from a new project to an approved team, by hand at the terminal."""

import json
from pathlib import Path

import pytest

from tests.cli.conftest import Cli, cli, data_dir
from tests.worktrees.conftest import isolated_git, remote, repo

# The CLI fixtures: a scratch data directory and a real git repository for the project.
__all__ = ["cli", "data_dir", "isolated_git", "remote", "repo"]

MEMBERS = [
    {"key": "back", "role": "lead", "title": "Backend lead", "adapter": "fake"},
    {"key": "dev", "role": "worker", "title": "Developer", "adapter": "fake", "reports_to": "back"},
]


def test_a_team_is_proposed_and_approved_through_the_cli(cli: Cli, repo: Path) -> None:
    cli.ok("init")
    cli.ok("project", "add", "site", "--repo", str(repo))
    assert "agent 1 CEO (ceo, fake): active" in cli.ok("org", "ceo", "--adapter", "fake")

    assigned = cli.ok("org", "assign-manager", "site", "--adapter", "fake")
    assert "agent 2 site manager (manager, fake, project 1): pending_approval" in assigned
    assert "approval 1: create_agent [light] pending" in assigned
    assert "approval 1: create_agent [light] executed" in cli.ok("approvals", "approve", "1")

    proposed = cli.ok("org", "propose-team", "2", "--members", json.dumps(MEMBERS))
    assert "approval 2: create_team [heavy] pending" in proposed
    assert len(cli.rows("SELECT id FROM agents")) == 2

    assert "approval 2: create_team [heavy] executed" in cli.ok("approvals", "approve", "2")
    rows = cli.rows("SELECT id, role, title, reports_to, status FROM agents ORDER BY id")
    assert [tuple(row) for row in rows[2:]] == [
        (3, "lead", "Backend lead", 2, "active"),
        (4, "worker", "Developer", 3, "active"),
    ]
    assert cli.ok("org", "tree").splitlines() == [
        "agent 1 CEO (ceo, fake): active",
        "  agent 2 site manager (manager, fake, project 1): active",
        "    agent 3 Backend lead (lead, fake, project 1): active",
        "      agent 4 Developer (worker, fake, project 1): active",
    ]


def test_a_team_past_the_cap_is_refused_at_the_cli(
    cli: Cli, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LABHQ_MAX_TEAM_SIZE", "1")
    cli.ok("init")
    cli.ok("project", "add", "site", "--repo", str(repo))
    cli.ok("org", "assign-manager", "site", "--adapter", "fake")
    cli.ok("approvals", "approve", "1")

    result = cli("org", "propose-team", "2", "--members", json.dumps(MEMBERS))

    assert result.exit_code == 1
    assert "team-size cap of 1" in result.stderr
    assert [row["type"] for row in cli.rows("SELECT type FROM approvals")] == ["create_agent"]


def test_invalid_member_json_is_reported(cli: Cli) -> None:
    cli.ok("init")

    result = cli("org", "propose-team", "2", "--members", "{not json")

    assert result.exit_code == 1
    assert "--members" in result.stderr
