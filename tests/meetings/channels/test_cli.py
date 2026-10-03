"""`labhq meetings start --meeting` mirrors the meeting it runs into the chat outbox."""

from pathlib import Path

from tests.cli.conftest import Cli, cli, data_dir
from tests.worktrees.conftest import isolated_git, remote, repo

# The CLI fixtures, with the git isolation the CLI tests run under.
__all__ = ["cli", "data_dir", "isolated_git", "remote", "repo"]


def test_a_meeting_run_from_the_cli_is_queued_for_its_thread(cli: Cli, repo: Path) -> None:
    cli.ok("init")
    cli.ok("project", "add", "site", "--repo", str(repo))
    cli.ok("agent", "add", "--project", "site", "--role", "lead", "--title", "Backend lead")
    cli.ok("agent", "approve", "1")
    cli.ok("meetings", "start", "site")
    cli.ok("approvals", "approve", "1")

    # The fake agent's minutes are not JSON, so the meeting fails; it is mirrored all the same.
    cli("meetings", "start", "--meeting", "1")

    rows = cli.rows("SELECT kind, persona_name, thread_key, status FROM chat_outbox ORDER BY id")
    kinds = [row["kind"] for row in rows]
    assert kinds[0] == "agenda"
    assert kinds[-1] == "minutes"
    assert "entry" in kinds
    assert {row["thread_key"] for row in rows} == {"meeting:1"}
    assert {row["status"] for row in rows} == {"pending"}
    assert "Backend lead (lead)" in {row["persona_name"] for row in rows}
