from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.channels import ChannelRuntime
from labhq.clock import FakeClock
from labhq.db import create_engine, session_factory
from labhq.notify import NotifySettings


@pytest.fixture
async def sessions(database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(database_url)
    try:
        yield session_factory(engine)
    finally:
        await engine.dispose()


class Outbound:
    """A MockTransport that records requests and answers with scripted status codes."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.statuses: list[int] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.statuses.pop(0) if self.statuses else 200)

    def hosts(self) -> list[str]:
        return [str(request.url.host) for request in self.requests]


@pytest.fixture
def outbound() -> Outbound:
    return Outbound()


@pytest.fixture
async def runtime(
    sessions: async_sessionmaker[AsyncSession],
    clock: FakeClock,
    outbound: Outbound,
    tmp_path: Path,
) -> AsyncIterator[ChannelRuntime]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(outbound))
    try:
        yield ChannelRuntime(sessions, client, tmp_path / "data", clock, NotifySettings())
    finally:
        await client.aclose()
