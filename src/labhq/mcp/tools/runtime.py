"""What every tool handler shares: its own database session and the system clock."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from labhq.clock import Clock, SystemClock
from labhq.db import create_engine, session_factory
from labhq.settings import Settings

CLOCK: Clock = SystemClock()


@asynccontextmanager
async def tool_session() -> AsyncIterator[AsyncSession]:
    # Settings are read per call, not cached: the data directory is the server's, and a
    # test must not need a restart to point at its own. One engine per call is cheap for
    # SQLite and leaves nothing open between calls.
    engine = create_engine(Settings().resolved_database_url)
    try:
        async with session_factory(engine)() as session:
            yield session
    finally:
        await engine.dispose()
