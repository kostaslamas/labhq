"""What every command shares: settings, the database, the clock and failure handling.

Commands are synchronous Typer functions that hand one coroutine to `execute`. It runs the
coroutine, turns the errors an operator can act on into one line on stderr and exit code 1,
and lets anything else surface as a traceback, which still exits non-zero.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import NoReturn

import typer
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.adapters import UnknownAdapterError
from labhq.approvals import ApprovalError, UnknownEntryError
from labhq.clock import Clock, SystemClock
from labhq.db import create_engine, session_factory
from labhq.settings import Settings
from labhq.worktrees import GitError, WorktreeError

FAILURE_EXIT_CODE = 1


class CliError(RuntimeError):
    """A failure the operator can fix; the message says how."""


# Errors whose message is enough for the operator; anything else keeps its traceback.
REPORTED_ERRORS: tuple[type[Exception], ...] = (
    CliError,
    ApprovalError,
    GitError,
    WorktreeError,
    UnknownAdapterError,
    UnknownEntryError,
    ValidationError,
    SQLAlchemyError,
)

MISSING_SCHEMA_HINT = "the database has no labhq schema yet; run `labhq init` first"


@dataclass(frozen=True)
class Context:
    settings: Settings
    sessions: async_sessionmaker[AsyncSession]
    clock: Clock


def load_settings() -> Settings:
    # Read on every command, not cached: one process may serve several invocations (tests).
    return Settings()


def make_clock() -> Clock:
    return SystemClock()


@asynccontextmanager
async def open_context() -> AsyncIterator[Context]:
    settings = load_settings()
    if settings.database_url is None and not settings.data_dir.exists():
        raise CliError(f"no labhq data in {settings.data_dir}; run `labhq init` first")
    engine = create_engine(settings.resolved_database_url)
    try:
        yield Context(settings, session_factory(engine), make_clock())
    finally:
        await engine.dispose()


def fail(message: str) -> NoReturn:
    typer.echo(f"error: {message}", err=True)
    raise typer.Exit(FAILURE_EXIT_CODE)


def _message(error: Exception) -> str:
    if isinstance(error, OperationalError) and "no such table" in str(error.orig):
        return MISSING_SCHEMA_HINT
    if isinstance(error, SQLAlchemyError):
        return f"database error: {getattr(error, 'orig', None) or error}"
    return str(error)


def execute[T](command: Callable[[Context], Awaitable[T]]) -> T:
    """Run `command` with a fresh context; report operator errors and exit 1 on them."""

    async def main() -> T:
        async with open_context() as context:
            return await command(context)

    try:
        return asyncio.run(main())
    except REPORTED_ERRORS as error:
        fail(_message(error))
