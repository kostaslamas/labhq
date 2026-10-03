import json
from pathlib import Path

import pytest

from labhq.worktrees.git import run_git
from tests.cli.conftest import Cli

DEMO = Path("demo") / "demo"


def remote_branches(remote: Path) -> dict[str, str]:
    listing = run_git("for-each-ref", "--format=%(refname:short) %(objectname)", cwd=remote)
    return dict(line.split(" ", 1) for line in listing.splitlines())


@pytest.fixture
def demo(cli: Cli) -> str:
    return cli.ok("demo")


def test_demo_produces_a_branch_with_a_commit(cli: Cli, demo: str) -> None:
    project = cli.data_dir / DEMO / "project"
    [task] = cli.rows("SELECT id FROM tasks")
    branch = run_git("for-each-ref", "--format=%(refname:short)", "refs/heads/labhq/", cwd=project)
    assert branch.strip().startswith(f"labhq/task-{task['id']}-")
    ahead = run_git("rev-list", "--count", f"main..{branch.strip()}", cwd=project)
    assert int(ahead) >= 1
    assert f"branch: {branch.strip()}" in demo


def test_demo_records_the_run_cost_in_micros(cli: Cli, demo: str) -> None:
    [run] = cli.rows("SELECT id, status, agent_id FROM runs")
    [cost] = cli.rows("SELECT * FROM cost_events")
    assert run["status"] == "succeeded"
    assert (cost["run_id"], cost["agent_id"]) == (run["id"], run["agent_id"])
    # The fake reports $0.0125, stored as integer micro-USD (ADR 0002).
    assert cost["cost_micros"] == 12_500
    assert f"cost_events {cost['id']}:" in demo


def test_demo_leaves_a_pending_push_that_is_not_executed(cli: Cli, demo: str) -> None:
    [approval] = cli.rows("SELECT * FROM approvals")
    payload = json.loads(approval["payload"])
    assert (approval["type"], approval["status"], approval["risk_class"]) == (
        "push",
        "pending",
        "heavy",
    )
    project = cli.data_dir / DEMO / "project"
    assert payload["commit"] == run_git("rev-parse", payload["branch"], cwd=project).strip()
    # Nothing reaches the remote before a human approves.
    assert payload["branch"] not in remote_branches(cli.data_dir / DEMO / "remote.git")
    assert f"commit: {payload['commit']}" in demo
    assert f"approvals approve {approval['id']}" in demo


def test_demo_has_one_manager_and_a_worker_reporting_to_it(cli: Cli, demo: str) -> None:
    agents = {row["role"]: row for row in cli.rows("SELECT * FROM agents")}
    assert set(agents) == {"manager", "worker"}
    assert agents["worker"]["reports_to"] == agents["manager"]["id"]
    [task] = cli.rows("SELECT assignee_id FROM tasks")
    assert task["assignee_id"] == agents["worker"]["id"]


def test_approving_the_push_publishes_the_branch_to_the_bare_remote(cli: Cli, demo: str) -> None:
    [approval] = cli.rows("SELECT id, payload FROM approvals")
    payload = json.loads(approval["payload"])

    cli.ok("approvals", "approve", str(approval["id"]))

    published = remote_branches(cli.data_dir / DEMO / "remote.git")
    assert published[payload["branch"]] == payload["commit"]
    [after] = cli.rows("SELECT status, decided_by, confirmation_kind FROM approvals")
    assert after["status"] == "executed"
    assert after["confirmation_kind"] == "cli"
    assert after["decided_by"].startswith("cli:")


def test_rejecting_the_push_publishes_nothing(cli: Cli, demo: str) -> None:
    [approval] = cli.rows("SELECT id, payload FROM approvals")

    cli.ok("approvals", "reject", str(approval["id"]), "--note", "not yet")

    branch = json.loads(approval["payload"])["branch"]
    assert branch not in remote_branches(cli.data_dir / DEMO / "remote.git")
    assert cli.rows("SELECT status FROM approvals")[0]["status"] == "rejected"


def test_a_second_demo_under_the_same_name_fails(cli: Cli, demo: str) -> None:
    result = cli("demo")
    assert result.exit_code == 1
    assert "already holds a demo" in result.stderr


def test_the_demo_runs_in_an_existing_repository(cli: Cli, repo: Path, remote: Path) -> None:
    output = cli.ok("demo", "--name", "mine", "--repo", str(repo))

    [approval] = cli.rows("SELECT id, payload FROM approvals")
    assert json.loads(approval["payload"])["url"] == str(remote)
    assert "approval 1: push [heavy] pending" in output
    cli.ok("approvals", "approve", str(approval["id"]))
    assert json.loads(approval["payload"])["branch"] in remote_branches(remote)
