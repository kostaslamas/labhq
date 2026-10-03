from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
from sqlalchemy import select

from labhq.chat import BindingStore, Channel, Persona, Reply, Thread
from labhq.chat.base import ChatError
from labhq.chat.fake import FakeChatAdapter, FakeChatService
from labhq.db.models import Meeting
from labhq.meetings.channels.drain import OutboxDrain
from labhq.meetings.channels.meeting_posts import MeetingMirror
from labhq.meetings.channels.models import ChatPost
from labhq.meetings.channels.settings import ChannelSettings
from tests.meetings.conftest import World

ADAPTER = "fake"


class SwitchableAdapter(FakeChatAdapter):
    """The fake adapter with a plug: while `down`, every call fails as a dead service would."""

    def __init__(self, service: FakeChatService, store: BindingStore) -> None:
        super().__init__(service, store)
        self.down = False

    def _check(self) -> None:
        if self.down:
            raise ChatError("service unavailable")

    async def ensure_channel(self, key: str, name: str) -> Channel:
        self._check()
        return await super().ensure_channel(key, name)

    async def open_thread(self, channel: Channel, title: str) -> Thread:
        self._check()
        return await super().open_thread(channel, title)

    async def post(self, thread: Thread, persona: Persona, text: str) -> list[str]:
        self._check()
        return await super().post(thread, persona, text)


@dataclass
class Bridge:
    world: World
    settings: ChannelSettings
    service: FakeChatService
    adapter: SwitchableAdapter
    drain: OutboxDrain

    async def flush(self) -> int:
        return await self.drain.drain(ADAPTER, self.adapter)

    def channel_names(self) -> list[str]:
        return list(self.service.channels.values())

    def posts(self, thread_id: str) -> list[tuple[str, str]]:
        return [(post.persona.name, post.text) for post in self.service.posts.get(thread_id, [])]

    async def thread_of(self, meeting_id: int) -> Thread:
        async with self.world.sessions() as db:
            meeting = await db.get_one(Meeting, meeting_id)
        assert meeting.channel_adapter == ADAPTER
        assert meeting.external_ref is not None
        channel_id = next(iter(self.service.channels))
        return Thread(Channel(f"project-{meeting.project_id}", channel_id), meeting.external_ref)

    def reply(self, thread: Thread, text: str, ref: str) -> Reply:
        return Reply(thread, "owner", text, ref)

    async def outbox(self) -> list[ChatPost]:
        async with self.world.sessions() as db:
            return list(await db.scalars(select(ChatPost).order_by(ChatPost.id)))


@pytest.fixture
async def bridge(world: World) -> AsyncIterator[Bridge]:
    # No generated avatars: tests compare personas by name and must not depend on a URL.
    settings = ChannelSettings(avatar_url_template="")
    MeetingMirror(world.sessions, world.clock, settings).install(world.listeners)
    service = FakeChatService()
    adapter = SwitchableAdapter(service, BindingStore(world.sessions, ADAPTER, clock=world.clock))
    yield Bridge(
        world=world,
        settings=settings,
        service=service,
        adapter=adapter,
        drain=OutboxDrain(world.sessions, world.clock, settings),
    )
    await adapter.close()
