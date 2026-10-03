from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.chat import BindingStore, Persona, Thread
from labhq.chat.base import ChatAdapter
from labhq.chat.contract import ChatHarness, Speaker
from labhq.chat.discord import DiscordAdapter, DiscordSettings
from labhq.chat.fake import FakeChatAdapter, FakeChatService, FakeInbound
from labhq.clock import Clock
from labhq.db import create_engine, session_factory
from tests.chat.fake_discord import (
    API,
    BOT_TOKEN,
    GUILD_ID,
    OWNER_ID,
    FakeDiscordApi,
    ScriptedGateway,
    SteppedClock,
)


@pytest.fixture
async def sessions(database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(database_url)
    try:
        yield session_factory(engine)
    finally:
        await engine.dispose()


@pytest.fixture
def stepped_clock() -> SteppedClock:
    return SteppedClock(datetime(2026, 10, 2, 9, 0, tzinfo=UTC))


def discord_settings(**overrides: object) -> DiscordSettings:
    values: dict[str, object] = {
        "bot_token": BOT_TOKEN,
        "guild_id": GUILD_ID,
        "owner_id": OWNER_ID,
        "api_base": API,
    }
    return DiscordSettings(**(values | overrides))  # type: ignore[arg-type]


class FakeHarness:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], clock: Clock) -> None:
        self.service = FakeChatService(owner_id="owner")
        self._sessions = sessions
        self._clock = clock

    async def make(self) -> ChatAdapter:
        return FakeChatAdapter(
            self.service, BindingStore(self._sessions, "fake", clock=self._clock)
        )

    def created_objects(self) -> int:
        return len(self.service.channels)

    def posts(self, thread: Thread) -> list[tuple[Persona, str]]:
        return [(post.persona, post.text) for post in self.service.posts.get(thread.id, [])]

    async def say(self, channel_id: str, speaker: Speaker, text: str) -> None:
        author_id = "owner" if speaker in (Speaker.OWNER, Speaker.BOT) else str(speaker)
        self.service.inbound.put_nowait(
            FakeInbound(
                channel_id,
                author_id,
                str(speaker),
                text,
                from_bot=speaker == Speaker.BOT,
                from_webhook=speaker == Speaker.WEBHOOK,
            )
        )


class DiscordHarness:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], clock: Clock) -> None:
        self.api = FakeDiscordApi()
        self.gateway = ScriptedGateway()
        self.client = self.api.client()
        self._sessions = sessions
        self._clock = clock
        self._sequence = 20

    async def make(self) -> ChatAdapter:
        return self.adapter()

    def adapter(self, **overrides: object) -> DiscordAdapter:
        return DiscordAdapter(
            settings=discord_settings(**overrides),
            store=BindingStore(self._sessions, "discord", clock=self._clock),
            client=self.client,
            clock=self._clock,
            connect=self.gateway.connect,
        )

    def created_objects(self) -> int:
        return self.api.created

    def posts(self, thread: Thread) -> list[tuple[Persona, str]]:
        return [
            (Persona(message["username"], message.get("avatar_url")), message["content"])
            for message in self.api.messages.get(thread.id, [])
        ]

    async def say(self, channel_id: str, speaker: Speaker, text: str) -> None:
        self._sequence += 1
        self.gateway.deliver(speaker, channel_id, text, self._sequence)


@pytest.fixture
def fake_harness(sessions: async_sessionmaker[AsyncSession], stepped_clock: SteppedClock):
    return FakeHarness(sessions, stepped_clock)


@pytest.fixture
async def discord_harness(
    sessions: async_sessionmaker[AsyncSession], stepped_clock: SteppedClock
) -> AsyncIterator[DiscordHarness]:
    harness = DiscordHarness(sessions, stepped_clock)
    async with harness.client:
        yield harness


@pytest.fixture(params=["fake", "discord"])
async def harness(
    request: pytest.FixtureRequest,
    sessions: async_sessionmaker[AsyncSession],
    stepped_clock: SteppedClock,
) -> AsyncIterator[ChatHarness]:
    """Every chat adapter in turn, so each contract check runs against all of them."""
    if request.param == "fake":
        yield FakeHarness(sessions, stepped_clock)
        return
    discord = DiscordHarness(sessions, stepped_clock)
    async with discord.client:
        yield discord
