"""`labhq rules`: add with a reason, list, and disable so evaluation skips the rule."""

import asyncio
import json
from pathlib import Path

from labhq.clock import FakeClock
from labhq.db import create_engine, session_factory
from labhq.health.incidents import IncidentChange, evaluate_rules
from labhq.settings import DATABASE_FILENAME, sqlite_url
from tests.cli.conftest import Cli
from tests.health.factories import add_host, add_samples

CPU_OVER_90 = json.dumps({"metric": "cpu.percent", "comparison": ">", "value": 90})


def _evaluate_with_hot_cpu(
    data_dir: Path, clock: FakeClock, host_name: str
) -> list[IncidentChange]:
    async def main() -> list[IncidentChange]:
        engine = create_engine(sqlite_url(data_dir / DATABASE_FILENAME))
        try:
            async with session_factory(engine)() as db, db.begin():
                host = await add_host(db, clock, host_name)
                await add_samples(db, host, "cpu.percent", [(clock.now(), 97.0)])
                return await evaluate_rules(db, clock)
        finally:
            await engine.dispose()

    return asyncio.run(main())


def test_a_rule_without_a_reason_is_refused(cli: Cli) -> None:
    cli.ok("init")
    result = cli("rules", "add", "threshold", "--params", CPU_OVER_90, "--reason", "  ")
    assert result.exit_code == 1
    assert "reason" in result.stderr
    assert cli.rows("SELECT id FROM health_rules") == []


def test_bad_params_are_refused(cli: Cli) -> None:
    cli.ok("init")
    for params in ('{"metric": "cpu.percent"}', "[1]", "not json"):
        result = cli("rules", "add", "threshold", "--params", params, "--reason", "why")
        assert result.exit_code == 1
        assert result.stderr.startswith("error: ")


def test_added_rules_are_listed_and_disabling_stops_evaluation(cli: Cli, clock: FakeClock) -> None:
    cli.ok("init")
    assert "no rules" in cli.ok("rules", "list")
    added = cli.ok(
        "rules",
        "add",
        "threshold",
        "--params",
        CPU_OVER_90,
        "--action",
        "ticket",
        "--reason",
        "Builds stall when the CPU is pinned",
        "--by",
        "agent:7",
        "--name",
        "cpu pinned",
    )
    assert added.strip() == "rule 1 added"
    listing = cli.ok("rules", "list")
    assert "rule 1 'cpu pinned': threshold -> ticket, enabled, by agent:7" in listing
    assert "reason 'Builds stall when the CPU is pinned'" in listing

    assert cli.ok("rules", "disable", "1").strip() == "rule 1 disabled"
    assert "disabled" in cli.ok("rules", "list")
    assert _evaluate_with_hot_cpu(cli.data_dir, clock, "one") == []
    assert cli.rows("SELECT id FROM incidents") == []

    assert cli.ok("rules", "enable", "1").strip() == "rule 1 enabled"
    # Enabled again, the rule watches both hosts that now run hot.
    assert len(_evaluate_with_hot_cpu(cli.data_dir, clock, "two")) == 2
    assert "incident 2 open" in cli.ok("rules", "list")
