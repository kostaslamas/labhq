"""The always-on program's `chat` loop: owner replies in, outbox out, through one adapter.

One pass opens the adapter, reads its replies in the background and drains the outbox every
`drain_interval_seconds` until the program stops. When the adapter fails the pass ends; the
program logs it and starts a fresh pass after `chat_interval_seconds`, which is how the reader
reconnects once the service is back. A post that fails waits in the outbox meanwhile. With no
chat adapter configured a pass does nothing.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.approvals.registry import Registry
from labhq.chat import ChatAdapter, ChatAdapterFactory, ChatContext, configured_chat_adapters
from labhq.clock import Clock
from labhq.meetings.channels.drain import OutboxDrain
from labhq.meetings.channels.inbound import receive
from labhq.meetings.channels.incidents import enqueue_incidents
from labhq.meetings.channels.settings import ChannelSettings, get_channel_settings
from labhq.meetings.events import MeetingListeners
from labhq.meetings.events import default_listeners as builtin_listeners


class ChannelLoop:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        clock: Clock,
        *,
        adapters: Registry[ChatAdapterFactory] | None = None,
        settings: ChannelSettings | None = None,
        listeners: MeetingListeners = builtin_listeners,
    ) -> None:
        self._sessions = sessions
        self._clock = clock
        self._adapters = adapters if adapters is not None else configured_chat_adapters()
        self._settings = settings or get_channel_settings()
        self._listeners = listeners
        self._drain = OutboxDrain(sessions, clock, self._settings)

    def adapter_name(self) -> str | None:
        """The adapter meetings are mirrored to: the chosen one, else the first configured."""
        if self._settings.adapter is not None:
            return self._settings.adapter if self._settings.adapter in self._adapters else None
        return next(iter(self._adapters), None)

    async def run(self) -> None:
        name = self.adapter_name()
        if name is None:
            return
        async with httpx.AsyncClient() as client:
            adapter = self._adapters.get(name)(ChatContext(self._sessions, client, self._clock))
            try:
                async with asyncio.TaskGroup() as group:
                    group.create_task(self.read(name, adapter))
                    while True:
                        await self.pass_once(name, adapter)
                        await self._clock.sleep(self._settings.drain_interval_seconds)
            finally:
                await adapter.close()

    async def pass_once(self, name: str, adapter: ChatAdapter) -> int:
        """Queue new incident transitions, then send what is due; returns posts sent."""
        async with self._sessions() as db:
            await enqueue_incidents(db, self._clock, self._settings)
            await db.commit()
        return await self._drain.drain(name, adapter)

    async def read(self, name: str, adapter: ChatAdapter) -> None:
        async for reply in adapter.replies():
            await receive(self._sessions, self._clock, name, reply, listeners=self._listeners)


class _Context(Protocol):
    @property
    def sessions(self) -> async_sessionmaker[AsyncSession]: ...

    @property
    def clock(self) -> Clock: ...


class _Services(Protocol):
    @property
    def context(self) -> _Context: ...


def chat_step(services: _Services) -> Callable[[], Awaitable[object]]:
    context = services.context
    return ChannelLoop(context.sessions, context.clock).run
