"""`labhq health`: the latest samples and the open incidents."""

import sqlite3
from contextlib import closing

from labhq.settings import DATABASE_FILENAME
from tests.cli.conftest import Cli


def test_health_before_any_sample(cli: Cli) -> None:
    cli.ok("init")
    output = cli.ok("health")
    assert "no samples yet" in output
    assert "0 open incidents" in output


def test_collect_shows_the_latest_pass_and_opens_incidents(cli: Cli) -> None:
    cli.ok("init")
    # A rule every machine violates: memory use is never below zero.
    with closing(sqlite3.connect(cli.data_dir / DATABASE_FILENAME)) as db:
        db.execute(
            "INSERT INTO health_rules (type, name, params, action, reason, created_by, enabled,"
            " created_at, updated_at) VALUES ('threshold', 'memory in use', ?, 'notify',"
            " 'test', 'test', 1, '2026-10-02 09:00:00', '2026-10-02 09:00:00')",
            ('{"metric": "memory.percent", "comparison": ">=", "value": 0}',),
        )
        db.commit()

    cli.ok("health", "--collect")
    output = cli.ok("health", "--collect")

    assert "memory.percent" in output
    # Two passes, but only the latest is shown.
    assert output.count("memory.percent") == 1
    assert "1 open incidents" in output
    assert "memory in use" in output
