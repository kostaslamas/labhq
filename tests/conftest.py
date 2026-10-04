from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.clock import FakeClock
from labhq.db import create_engine, session_factory
from labhq.settings import sqlite_url

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No test reads the developer's own data directory (a persisted public URL, say)."""
    monkeypatch.setenv("LABHQ_DATA_DIR", str(tmp_path / "isolated-data"))


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(datetime(2026, 10, 2, 9, 0, tzinfo=UTC))


def alembic_config(url: str) -> Config:
    # No ini file: tests must not reconfigure logging or read the developer's database.
    config = Config()
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    """A scratch SQLite database migrated to head. Sync, because env.py runs its own loop."""
    url = sqlite_url(tmp_path / "labhq.sqlite3")
    command.upgrade(alembic_config(url), "head")
    return url


@pytest.fixture
async def session(database_url: str) -> AsyncIterator[AsyncSession]:
    engine = create_engine(database_url)
    try:
        async with session_factory(engine)() as db_session:
            yield db_session
    finally:
        await engine.dispose()
