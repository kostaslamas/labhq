"""Alembic environment: async SQLAlchemy, URL from labhq settings, SQLite batch mode."""

import asyncio
from logging.config import fileConfig
from typing import Any

from alembic import context
from alembic.autogenerate.api import AutogenContext
from sqlalchemy import Enum, pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

import labhq.db.models  # noqa: F401  (registers every table on the metadata)
from labhq.db.base import Base, UTCDateTime

# Kept out of `labhq.db.models`: its package imports the meeting engine, which imports those.
from labhq.meetings.channels.models import ChatPost  # noqa: F401
from labhq.settings import get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _database_url() -> str:
    # Tests pass an explicit URL through the Config; everything else uses settings.
    explicit = config.get_main_option("sqlalchemy.url")
    if explicit:
        return explicit
    settings = get_settings()
    if settings.database_url is None:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings.resolved_database_url


url = _database_url()


def render_item(type_: str, obj: Any, autogen_context: AutogenContext) -> str | bool:
    # Migrations stay independent of application types. UTCDateTime is a plain DateTime
    # column with timezone handling in the model layer. A vocabulary is a string column
    # whose named CHECK constraint is rendered from the table, so the Enum must not add a
    # second, unnamed one.
    if type_ != "type":
        return False
    if isinstance(obj, UTCDateTime):
        return "sa.DateTime(timezone=True)"
    if isinstance(obj, Enum):
        return f"sa.String(length={obj.length})"
    return False


def _configure(**kwargs: Any) -> None:
    context.configure(
        target_metadata=target_metadata,
        render_as_batch=True,
        compare_type=True,
        render_item=render_item,
        **kwargs,
    )


def run_migrations_offline() -> None:
    _configure(url=url, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        {"sqlalchemy.url": url}, prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        do_run_migrations(connection)
        return
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
