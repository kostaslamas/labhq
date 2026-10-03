"""`labhq it`: the operator starts the IT agent, then a pass queues what it is due."""

import pytest

from tests.cli.conftest import Cli, cli

__all__ = ["cli"]


def test_the_operator_starts_one_it_agent_and_wakes_it(
    cli: Cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Midnight has always passed, whatever the wall clock says: the report is due.
    monkeypatch.setenv("LABHQ_IT_REPORT_TIME", "00:00")
    cli.ok("init")
    assert cli.ok("it", "wake").strip() == "no IT agent; create one with `labhq it start`"

    started = cli.ok("it", "start", "--adapter", "fake")
    again = cli.ok("it", "start", "--adapter", "fake")

    assert started == again
    assert started.strip() == "agent 2 IT (it, fake, read-only): active"
    rows = cli.rows("SELECT id, role, project_id, reports_to, config FROM agents ORDER BY id")
    assert [tuple(row) for row in rows] == [
        (1, "ceo", None, None, "{}"),
        (2, "it", None, 1, '{"permission_mode": "read_only"}'),
    ]
    assert cli.ok("it", "wake").strip() == "report wakeup 1: created"
    assert cli.ok("it", "wake").strip() == "report wakeup 1: duplicate"


def test_an_unknown_adapter_is_refused(cli: Cli) -> None:
    cli.ok("init")
    result = cli("it", "start", "--adapter", "nope")
    assert result.exit_code == 1
    assert "no adapter registered as 'nope'" in result.output
