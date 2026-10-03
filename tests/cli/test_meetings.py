"""`labhq meetings start|list|show`: request through the meeting service, read from the database."""

import asyncio
from pathlib import Path

import pytest

from labhq.clock import FakeClock
from labhq.db import create_engine, session_factory
from labhq.settings import DATABASE_FILENAME, sqlite_url
from tests.callcenter.answers.minutes_seed import Team, add_meeting
from tests.cli.conftest import Cli, plain


def _project_with_lead(cli: Cli, repo: Path) -> None:
    cli.ok("init")
    cli.ok("project", "add", "site", "--repo", str(repo))
    cli.ok("agent", "add", "--project", "site", "--role", "lead", "--title", "Backend lead")
    # New agents wait for approval, and only active ones attend by default.
    cli.ok("agent", "approve", "1")


def _seed_minutes(data_dir: Path, clock: FakeClock) -> int:
    async def main() -> int:
        engine = create_engine(sqlite_url(data_dir / DATABASE_FILENAME))
        try:
            async with session_factory(engine)() as db:
                return await add_meeting(db, Team(project_id=1, lead_id=1), clock.now())
        finally:
            await engine.dispose()

    return asyncio.run(main())


@pytest.mark.parametrize("args", [(), ("start",), ("list",), ("show",)])
def test_every_command_has_help(cli: Cli, args: tuple[str, ...]) -> None:
    assert "Usage" in cli.ok("meetings", *args, "--help")


def test_start_requests_a_meeting_and_its_approval(cli: Cli, repo: Path) -> None:
    _project_with_lead(cli, repo)

    out = cli.ok("meetings", "start", "site", "--kind", "standup")

    assert out.startswith("meeting 1 requested: standup [requested]")
    assert "labhq approvals approve 1" in out
    assert "labhq meetings start --meeting 1" in out
    approvals = cli.rows("SELECT type, status FROM approvals")
    assert [tuple(row) for row in approvals] == [("start_meeting", "pending")]
    assert "meeting 1 (M1): standup for site [requested]" in cli.ok("meetings", "list")


def test_start_with_meeting_runs_an_approved_meeting_through_its_agents(
    cli: Cli, repo: Path
) -> None:
    _project_with_lead(cli, repo)
    cli.ok("meetings", "start", "site")
    refused = cli("meetings", "start", "--meeting", "1")
    assert refused.exit_code == 1
    assert "has no approved start" in refused.stderr

    cli.ok("approvals", "approve", "1")
    # The built-in fake agent answers every turn, but its minutes are not the JSON asked for.
    result = cli("meetings", "start", "--meeting", "1")

    assert result.exit_code == 1
    assert "meeting 1: standup [failed] (invalid_minutes)" in result.stdout
    shown = cli.ok("meetings", "show", "1")
    assert "[Backend lead]" in shown
    assert "Meeting failed: the minutes were not valid JSON." in shown


def test_start_needs_a_project_or_a_meeting_but_not_both(cli: Cli, repo: Path) -> None:
    _project_with_lead(cli, repo)
    for args in ((), ("site", "--meeting", "1")):
        result = cli("meetings", "start", *args)
        assert result.exit_code == 1
        assert "or --meeting" in result.stderr


def test_list_filters_and_says_when_there_is_nothing(cli: Cli, repo: Path) -> None:
    _project_with_lead(cli, repo)
    assert cli.ok("meetings", "list").strip() == "no meetings"
    cli.ok("meetings", "start", "site")

    assert cli.ok("meetings", "list", "--kind", "review").strip() == "no meetings"
    assert cli.ok("meetings", "list", "--status", "ended").strip() == "no meetings"
    assert "meeting 1" in cli.ok("meetings", "list", "--project", "site", "--status", "requested")


def test_show_prints_transcript_decisions_and_action_items(
    cli: Cli, repo: Path, clock: FakeClock
) -> None:
    _project_with_lead(cli, repo)
    meeting_id = _seed_minutes(cli.data_dir, clock)

    out = cli.ok("meetings", "show", str(meeting_id))

    assert f"meeting {meeting_id}: standup for site [ended]" in out
    assert "  [Backend lead] done the parser, next the tests" in out
    assert "  1. Ship the parser first" in out
    assert "  - Write parser tests -> agent 1, task 1 [todo]" in out


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (("start", "nope"), "no project 'nope'"),
        (("start", "site", "--kind", "retro"), "no meeting kind registered as 'retro'"),
        (("start", "site", "--participant", "99"), "no agents [99]"),
        (("list", "--project", "nope"), "no project 'nope'"),
        (("show", "42"), "no meeting 42"),
    ],
)
def test_failures_exit_non_zero_with_one_line(
    cli: Cli, repo: Path, args: tuple[str, ...], message: str
) -> None:
    _project_with_lead(cli, repo)

    result = cli("meetings", *args)

    assert result.exit_code == 1
    assert plain(result.stderr).strip() == f"error: {message}"


def test_a_project_without_attendees_cannot_meet(cli: Cli, repo: Path) -> None:
    cli.ok("init")
    cli.ok("project", "add", "empty", "--repo", str(repo))

    result = cli("meetings", "start", "empty")

    assert result.exit_code == 1
    assert "has no agents for a standup meeting" in result.stderr
    assert cli.rows("SELECT id FROM meetings") == []


def test_commands_before_init_fail(cli: Cli) -> None:
    for args in (("list",), ("show", "1"), ("start", "site")):
        result = cli("meetings", *args)
        assert result.exit_code == 1
        assert "labhq init" in result.stderr
