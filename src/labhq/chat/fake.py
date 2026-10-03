"""An in-memory chat service and its adapter, for tests and for the contract's own tests."""

import asyncio
import itertools
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from labhq.chat.base import Channel, ChatError, Persona, Reply, Thread
from labhq.chat.bindings import BindingStore
from labhq.chat.text import split_message
from labhq.db.models.chat import ChatBindingKind

FAKE_MESSAGE_LIMIT = 2000


@dataclass(frozen=True)
class FakeInbound:
    channel_id: str
    author_id: str
    author: str
    text: str
    from_bot: bool = False
    from_webhook: bool = False


@dataclass(frozen=True)
class FakePost:
    persona: Persona
    text: str


@dataclass
class FakeChatService:
    """The remote side: what exists on the service and what has been said there."""

    owner_id: str = "owner"
    channels: dict[str, str] = field(default_factory=dict)
    threads: dict[str, str] = field(default_factory=dict)
    posts: dict[str, list[FakePost]] = field(default_factory=dict)
    inbound: asyncio.Queue[FakeInbound] = field(default_factory=asyncio.Queue)
    _ids: "itertools.count[int]" = field(default_factory=lambda: itertools.count(1000))

    def new_id(self) -> str:
        return str(next(self._ids))


class FakeChatAdapter:
    max_message_length = FAKE_MESSAGE_LIMIT

    def __init__(self, service: FakeChatService, store: BindingStore) -> None:
        self._service = service
        self._store = store
        self._closed = asyncio.Event()

    async def ensure_channel(self, key: str, name: str) -> Channel:
        async def create() -> str:
            channel_id = self._service.new_id()
            self._service.channels[channel_id] = name
            return channel_id

        return Channel(key, await self._store.ensure(ChatBindingKind.CHANNEL, key, create))

    async def open_thread(self, channel: Channel, title: str) -> Thread:
        if channel.id not in self._service.channels:
            raise ChatError(f"unknown channel {channel.id}")
        thread = Thread(channel, self._service.new_id())
        self._service.threads[thread.id] = title
        await self._store.bind_thread(thread)
        return thread

    async def post(self, thread: Thread, persona: Persona, text: str) -> list[str]:
        posts = self._service.posts.setdefault(thread.id, [])
        refs = []
        for part in split_message(text, self.max_message_length):
            posts.append(FakePost(persona, part))
            refs.append(self._service.new_id())
        return refs

    async def replies(self) -> AsyncIterator[Reply]:
        while (message := await self._next_inbound()) is not None:
            if message.from_bot or message.from_webhook:
                continue
            if message.author_id != self._service.owner_id:
                continue
            thread = await self._store.labhq_thread(message.channel_id)
            if thread is not None:
                yield Reply(thread, message.author, message.text, self._service.new_id())

    async def close(self) -> None:
        self._closed.set()

    async def _next_inbound(self) -> FakeInbound | None:
        # The queue belongs to the service, which outlives a closed adapter, so close is an
        # adapter-local event rather than a sentinel in the shared queue.
        message = asyncio.ensure_future(self._service.inbound.get())
        closed = asyncio.ensure_future(self._closed.wait())
        await asyncio.wait({message, closed}, return_when=asyncio.FIRST_COMPLETED)
        message.cancel()
        closed.cancel()
        if self._closed.is_set() or message.cancelled():
            return None
        return message.result()
