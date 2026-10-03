"""Step: the database exists and its schema is at the latest migration."""

import asyncio
from types import ModuleType

from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection
from sqlalchemy.exc import SQLAlchemyError

from labhq.db import create_engine
from labhq.onboard.base import Detection, ManualAction, OnboardContext, Outcome, StepError
from labhq.settings import DATABASE_FILENAME


def _revision(connection: Connection) -> str | None:
    return MigrationContext.configure(connection).get_current_revision()


async def current_revision(url: str) -> str | None:
    engine = create_engine(url)
    try:
        async with engine.connect() as connection:
            return await connection.run_sync(_revision)
    finally:
        await engine.dispose()


def _cli_work() -> ModuleType:
    # Imported late: `labhq.cli` imports the onboarding command, which imports this module.
    from labhq.cli import work

    return work


class DatabaseStep:
    name = "database"
    required = True

    def detect(self, context: OnboardContext) -> Detection:
        settings = context.settings
        if settings.database_url is None and not (settings.data_dir / DATABASE_FILENAME).exists():
            return Detection(False, f"no database yet in {settings.data_dir}")
        revision = self._revision(context)
        if revision is None:
            return Detection(False, "the database has no labhq schema yet")
        return Detection(True, f"kept, schema at {revision}")

    def manual(self, context: OnboardContext, detection: Detection) -> ManualAction | None:
        return None

    def automate(self, context: OnboardContext) -> None:
        work = _cli_work()
        try:
            context.settings.data_dir.mkdir(parents=True, exist_ok=True)
            work.migrate(context.settings.resolved_database_url)
        except (work.CliError, OSError, SQLAlchemyError) as error:
            raise StepError(f"migration failed: {error}") from error

    def verify(self, context: OnboardContext) -> Outcome:
        head = ScriptDirectory(str(_cli_work().MIGRATIONS)).get_current_head()
        revision = self._revision(context)
        if revision != head:
            raise StepError(f"schema at {revision}, expected {head}")
        return Outcome(f"schema at {revision}")

    @staticmethod
    def _revision(context: OnboardContext) -> str | None:
        try:
            return asyncio.run(current_revision(context.settings.resolved_database_url))
        except SQLAlchemyError as error:
            raise StepError(f"cannot read the database: {error}") from error
