"""The Phase 1 demo with the fake adapter, and the push that follows its approval."""

import re
from pathlib import Path

from labhq.worktrees.git import run_git
from tests.cli.conftest import Cli
from tests.worktrees.gitrepo import head

APPROVAL = re.compile(r"^approval (\d+) pending: push to (.+)$", re.MULTILINE)


def remote_branches(remote: Path) -> str:
    return run_git("for-each-ref", "--format=%(refname) %(objectname)", cwd=remote)


def demo_approval_id(output: str) -> int:
    match = APPROVAL.search(output)
    assert match is not None, output
    return int(match.group(1))


def test_demo_leaves_a_commit_a_cost_row_and_a_pending_push(cli: Cli, repo: Path) -> None:
    output = cli.ok("demo", "--repo", str(repo))

    [(branch, commit, status)] = cli.rows(
        "SELECT json_extract(payload, '$.branch'), json_extract(payload, '$.commit'), status "
        "FROM approvals WHERE type = 'push'"
    )
    assert status == "pending"
    assert branch.startswith("labhq/task-")
    assert int(run_git("rev-list", "--count", f"main..{branch}", cwd=repo)) >= 1
    assert head(repo, branch) == commit
    assert f"branch {branch}" in output and f"commit {commit}" in output

    [(run_status,)] = cli.rows("SELECT status FROM runs")
    assert run_status == "succeeded"
    [(cost_micros, run_id)] = cli.rows("SELECT cost_micros, run_id FROM cost_events")
    assert cost_micros == 12_500 and run_id == 1
    assert {role for (role,) in cli.rows("SELECT role FROM agents")} == {"manager", "worker"}
    [(reports_to,)] = cli.rows("SELECT reports_to FROM agents WHERE role = 'worker'")
    assert reports_to is not None


def test_nothing_is_pushed_before_the_approval(cli: Cli, repo: Path, remote: Path) -> None:
    cli.ok("demo", "--repo", str(repo))
    assert "labhq/task-" not in remote_branches(remote)


def test_approve_pushes_the_branch_to_the_bare_remote(cli: Cli, repo: Path, remote: Path) -> None:
    approval_id = demo_approval_id(cli.ok("demo", "--repo", str(repo)))

    output = cli.ok("approvals", "approve", str(approval_id))

    [(branch, commit, status)] = cli.rows(
        "SELECT json_extract(payload, '$.branch'), json_extract(payload, '$.commit'), status "
        "FROM approvals WHERE id = ?",
        approval_id,
    )
    assert status == "executed"
    assert f"refs/heads/{branch} {commit}" in remote_branches(remote)
    assert "executed" in output


def test_reject_pushes_nothing(cli: Cli, repo: Path, remote: Path) -> None:
    approval_id = demo_approval_id(cli.ok("demo", "--repo", str(repo)))

    cli.ok("approvals", "reject", str(approval_id), "--note", "not now")

    assert cli.rows("SELECT status FROM approvals") == [("rejected",)]
    assert "labhq/task-" not in remote_branches(remote)


def test_the_default_demo_builds_its_own_sandbox(cli: Cli) -> None:
    output = cli.ok("demo")
    approval_id = demo_approval_id(output)
    match = APPROVAL.search(output)
    assert match is not None
    sandbox_remote = Path(match.group(2))
    assert sandbox_remote.is_relative_to(cli.data_dir)

    cli.ok("approvals", "approve", str(approval_id))

    assert "refs/heads/labhq/task-1-" in remote_branches(sandbox_remote)


def test_a_second_demo_gets_its_own_project(cli: Cli, repo: Path) -> None:
    cli.ok("demo", "--repo", str(repo))
    cli.ok("demo", "--repo", str(repo))
    assert cli.rows("SELECT name FROM projects ORDER BY id") == [("demo",), ("demo-2",)]
    assert len(cli.rows("SELECT id FROM approvals WHERE status = 'pending'")) == 2
