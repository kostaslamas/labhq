from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.api.deps import Owner, ResolverRegistry
from labhq.api.settings import ApiSettings
from labhq.db import create_engine, session_factory
from labhq.live.broker import Broker

OWNER_HEADER = "X-Test-Owner"


async def header_resolver(request: Request) -> Owner | None:
    """A stand-in for Passkeys: whoever sends the test header is the owner."""
    subject = request.headers.get(OWNER_HEADER)
    return Owner(subject) if subject else None


@pytest.fixture
def resolvers() -> ResolverRegistry:
    registry = ResolverRegistry()
    registry.register("test-header", header_resolver)
    return registry


@pytest.fixture
def api_settings(tmp_path: Path) -> ApiSettings:
    return ApiSettings(ui_dir=tmp_path / "no-ui")


@pytest.fixture
def broker() -> Iterator[Broker]:
    broker = Broker()
    yield broker
    broker.close_all()


@pytest.fixture
async def sessions(database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """The program's sessions; writers in the tests use an engine of their own."""
    engine = create_engine(database_url)
    try:
        yield session_factory(engine)
    finally:
        await engine.dispose()
