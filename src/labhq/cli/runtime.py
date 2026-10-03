"""What every command shares: settings, the database, migrations and failure reporting.

Commands are synchronous Typer callbacks that run one coroutine each. A failure the
operator can act on is printed as one `error:` line with exit status 1; anything else is a
bug and keeps its traceback, which still exits non-zero.
"""

import asyncio
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from decimal import InvalidOperation
from pathlib import Path

import typer
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import labhq
from labhq.adapters import UnknownAdapterError
from labhq.approvals import ApprovalError, UnknownEntryError
from labhq.db import create_engine, session_factory
from labhq.money import usd_to_micros
from labhq.settings import Settings
from labhq.worktrees import GitError, WorktreeError

# Migrations ship with the source tree, next to `src/`, in Phase 1.
MIGRATIONS_DIR = Path(labhq.__file__).resolve().parents[2] / "migrations"


class CliError(RuntimeError):
    """A failure the operator can act on; its message says what to do."""


# Expected failures, mapped to the advice printed after the message. Anything outside this
# table is a bug and keeps its traceback.
ERROR_HINTS: dict[type[Exception], str] = {
    CliError: "",
    ApprovalError: "",
    UnknownAdapterError: "",
    UnknownEntryError: "",
    GitError: "",
    WorktreeError: "",
    ValueError: "",
    IntegrityError: "it conflicts with an existing row",
    OperationalError: "has `labhq init` run against this database?",
}
EXPECTED_ERRORS = tuple(ERROR_HINTS)


def settings() -> Settings:
    # Read per command, never cached, so the environment of this invocation decides.
    return Settings()


def fail(message: str) -> typer.Exit:
    typer.echo(f"error: {message}", err=True)
    return typer.Exit(code=1)


def _hint_for(error: Exception) -> str:
    for kind in type(error).__mro__:
        hint = ERROR_HINTS.get(kind)
        if hint:
            return hint
    return ""


def describe(error: Exception) -> str:
    message = str(getattr(error, "orig", None) or error)
    hint = _hint_for(error)
    return f"{message} ({hint})" if hint else message


@contextmanager
def reported() -> Iterator[None]:
    """Turn an expected failure into an `error:` line and exit status 1."""
    try:
        yield
    except EXPECTED_ERRORS as error:
        raise fail(describe(error)) from error


Job = Callable[[async_sessionmaker[AsyncSession]], Awaitable[None]]


def sqlite_file(url: str) -> Path | None:
    """The file behind a SQLite URL; None for another backend or an in-memory database."""
    parsed = make_url(url)
    if parsed.get_backend_name() != "sqlite" or parsed.database in (None, "", ":memory:"):
        return None
    return Path(parsed.database)


def require_database(url: str) -> None:
    # Checked before connecting: a failed aiosqlite connect can outlive the event loop.
    path = sqlite_file(url)
    if path is not None and not path.is_file():
        raise CliError(f"no database at {path}; run `labhq init` first")


def run_with_database(job: Job, config: Settings | None = None) -> None:
    """Run `job` against the configured database, reporting expected failures."""
    url = (config or settings()).resolved_database_url

    async def main() -> None:
        engine = create_engine(url)
        try:
            await job(session_factory(engine))
        finally:
            await engine.dispose()

    with reported():
        require_database(url)
        asyncio.run(main())


def migrate(config: Settings) -> str:
    """Upgrade the database to the newest migration and return its URL."""
    if not (MIGRATIONS_DIR / "env.py").is_file():
        raise CliError(f"migrations not found at {MIGRATIONS_DIR}; run labhq from its source tree")
    if config.database_url is None:
        config.data_dir.mkdir(parents=True, exist_ok=True)
    url = config.resolved_database_url
    path = sqlite_file(url)
    if path is not None and not path.parent.is_dir():
        raise CliError(f"cannot create the database: {path.parent} does not exist")
    # No ini file: the URL comes from labhq settings and logging stays as it is.
    alembic = Config()
    alembic.set_main_option("script_location", str(MIGRATIONS_DIR))
    alembic.set_main_option("sqlalchemy.url", url)
    command.upgrade(alembic, "head")
    return url


def parse_usd(value: str | None) -> int | None:
    """A budget typed as dollars, e.g. `5` or `0.25`, in integer micro-USD (ADR 0002)."""
    if value is None:
        return None
    try:
        return usd_to_micros(value)
    except (InvalidOperation, ValueError) as error:
        raise CliError(f"{value!r} is not an amount in USD") from error
