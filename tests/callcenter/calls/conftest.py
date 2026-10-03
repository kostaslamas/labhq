import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.adapters import AdapterEvent, FakeAdapter, FakeScript, default_registry
from labhq.callcenter.calls import CallCenter
from labhq.callcenter.calls.settings import CallAgentSettings
from labhq.callcenter.settings import CallCenterSettings
from labhq.clock import FakeClock
from labhq.db import create_engine, session_factory
from labhq.db.models import CallRequest

WINDOW = CallCenterSettings(call_window_seconds=300, ticket_expiry_seconds=3600)
ANSWER = "Worker is wiring the login form. Its status is fresh, from a minute ago."


class SlowFakeAdapter(FakeAdapter):
    """A fake agent whose turn takes `seconds` of real time before it streams anything."""

    def __init__(self, script: FakeScript, seconds: float) -> None:
        super().__init__(script)
        self._seconds = seconds

    async def events(self) -> AsyncIterator[AdapterEvent]:
        await asyncio.sleep(self._seconds)
        async for event in super().events():
            yield event


class GatedFakeAdapter(FakeAdapter):
    """A fake agent whose turn lasts until the test opens the gate."""

    def __init__(self, script: FakeScript, gate: asyncio.Event) -> None:
        super().__init__(script)
        self._gate = gate

    async def events(self) -> AsyncIterator[AdapterEvent]:
        await self._gate.wait()
        async for event in super().events():
            yield event


@dataclass
class Line:
    center: CallCenter
    sessions: async_sessionmaker[AsyncSession]
    clock: FakeClock
    fake: FakeScript
    gate: asyncio.Event

    async def request(self, ticket: str) -> CallRequest:
        async with self.sessions() as db:
            return await db.get_one(
                CallRequest,
                await db.scalar(select(CallRequest.id).where(CallRequest.request_id == ticket)),
            )

    def after_window(self) -> None:
        self.clock.advance(timedelta(seconds=WINDOW.call_window_seconds + 1))


@pytest.fixture
async def sessions(database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(database_url)
    try:
        yield session_factory(engine)
    finally:
        await engine.dispose()


@pytest.fixture
async def line(sessions: async_sessionmaker[AsyncSession], clock: FakeClock) -> AsyncIterator[Line]:
    fake = FakeScript(text=ANSWER)
    registry = default_registry.copy()
    registry.register("fake", lambda: FakeAdapter(fake), replace=True)
    gate = asyncio.Event()
    registry.register("slow", lambda: SlowFakeAdapter(fake, 30), replace=True)
    registry.register("gated", lambda: GatedFakeAdapter(fake, gate), replace=True)
    center = CallCenter(
        sessions,
        clock,
        adapters=registry,
        settings=WINDOW,
        agent_settings=CallAgentSettings(agent_adapter="fake"),
    )
    try:
        yield Line(center, sessions, clock, fake, gate)
    finally:
        await center.close()
