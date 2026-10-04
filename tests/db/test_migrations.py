from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

import labhq.db.models  # noqa: F401
from labhq.db import Base
from labhq.meetings.channels.models import ChatPost  # noqa: F401
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
    "chat_outbox",
}
# Passkeys and web sessions (issue #62).
PHASE_4_TABLES = {"passkey_credentials", "web_sessions", "webauthn_challenges"}
ALL_TABLES = PHASE_1_TABLES | PHASE_2_TABLES | TMUX_TABLES | PHASE_3_TABLES | PHASE_4_TABLES


def _sync_url(async_url: str) -> str:
    return async_url.replace("sqlite+aiosqlite", "sqlite")


def test_models_declare_exactly_the_known_tables() -> None:
    assert set(Base.metadata.tables) == ALL_TABLES


def test_the_chain_has_a_single_head() -> None:
    heads = ScriptDirectory.from_config(alembic_config("sqlite://")).get_heads()
    assert heads == ["0012"]


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


def test_owner_message_upgrade_keeps_existing_wakeups(tmp_path: Path) -> None:
    url = sqlite_url(tmp_path / "with-wakeups.sqlite3")
    config = alembic_config(url)
    command.upgrade(config, "0011")
    engine = create_engine(_sync_url(url))
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO agents "
                "(id, role, title, adapter, config, status, created_at, updated_at) "
                "VALUES (1, 'ceo', 'CEO', 'claude', '{}', 'active', '2026-10-04', '2026-10-04')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO wakeup_requests "
                "(id, agent_id, source, reason, status, coalesced_count, idempotency_key, "
                "created_at, updated_at) VALUES "
                "(1, 1, 'timer', 'existing', 'pending', 0, 'old', '2026-10-04', '2026-10-04')"
            )
        )
    engine.dispose()

    command.upgrade(config, "head")

    engine = create_engine(_sync_url(url))
    with engine.begin() as connection:
        existing = connection.execute(text("SELECT reason FROM wakeup_requests WHERE id = 1"))
        assert existing.scalar() == "existing"
        connection.execute(
            text(
                "INSERT INTO wakeup_requests "
                "(agent_id, source, reason, status, coalesced_count, idempotency_key, "
                "created_at, updated_at) VALUES "
                "(1, 'owner_message', 'hello', 'pending', 0, 'new', '2026-10-04', '2026-10-04')"
            )
        )
    engine.dispose()


@pytest.mark.parametrize("table", sorted(ALL_TABLES))
def test_every_amount_column_is_integer_micros(table: str) -> None:
    for column in Base.metadata.tables[table].columns:
        if "cost" in column.name or "budget" in column.name:
            assert column.name.endswith("_micros"), f"{table}.{column.name}"
            assert column.type.python_type is int, f"{table}.{column.name}"
