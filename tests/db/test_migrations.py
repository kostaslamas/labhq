from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

import labhq.db.models  # noqa: F401
from labhq.db import Base
from labhq.settings import sqlite_url
from tests.conftest import alembic_config

PHASE_1_TABLES = {
    "projects",
    "agents",
    "tasks",
    "comments",
    "wakeup_requests",
    "runs",
    "run_events",
    "cost_events",
    "approvals",
    "budget_warnings",
    "agent_task_sessions",
    "hosts",
    "health_samples",
    "health_rules",
    "incidents",
}


PHASE_2_TABLES = {
    "calls",
    "call_requests",
    "deliveries",
    "agent_questions",
    "status_updates",
    "notifications",
}
# ADR 0003, the tmux adapter.
TMUX_TABLES = {"usage_readings"}
PHASE_3_TABLES = {
    "chat_bindings",
    "meetings",
    "meeting_participants",
    "meeting_transcript_entries",
    "meeting_decisions",
    "meeting_action_items",
}
ALL_TABLES = PHASE_1_TABLES | PHASE_2_TABLES | TMUX_TABLES | PHASE_3_TABLES


def _sync_url(async_url: str) -> str:
    return async_url.replace("sqlite+aiosqlite", "sqlite")


def test_models_declare_exactly_the_known_tables() -> None:
    assert set(Base.metadata.tables) == ALL_TABLES


def test_the_chain_has_a_single_head() -> None:
    heads = ScriptDirectory.from_config(alembic_config("sqlite://")).get_heads()
    assert heads == ["0006"]


def test_upgrade_head_builds_the_full_schema_from_empty(database_url: str) -> None:
    engine = create_engine(_sync_url(database_url))
    with engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
    engine.dispose()
    assert tables == ALL_TABLES | {"alembic_version"}


def test_migrations_and_models_do_not_drift(database_url: str) -> None:
    # The same comparison `alembic check` runs in CI.
    engine = create_engine(_sync_url(database_url))
    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection, opts={"compare_type": True, "render_as_batch": True}
        )
        diff = compare_metadata(context, Base.metadata)
    engine.dispose()
    assert diff == []


def test_downgrade_to_base_and_upgrade_again(tmp_path: Path) -> None:
    url = sqlite_url(tmp_path / "roundtrip.sqlite3")
    config = alembic_config(url)
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    engine = create_engine(_sync_url(url))
    with engine.connect() as connection:
        assert set(inspect(connection).get_table_names()) == {"alembic_version"}
    engine.dispose()
    command.upgrade(config, "head")


@pytest.mark.parametrize("table", sorted(ALL_TABLES))
def test_every_amount_column_is_integer_micros(table: str) -> None:
    for column in Base.metadata.tables[table].columns:
        if "cost" in column.name or "budget" in column.name:
            assert column.name.endswith("_micros"), f"{table}.{column.name}"
            assert column.type.python_type is int, f"{table}.{column.name}"
