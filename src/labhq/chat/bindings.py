"""Remote ids of what an adapter created, kept in `chat_bindings` across restarts."""

import asyncio
from collections.abc import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.chat.base import Channel, Thread
from labhq.clock import Clock
from labhq.db.models.chat import ChatBinding, ChatBindingKind


class BindingStore:
    """The bindings of one adapter. Only ids are stored, never tokens."""

    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], adapter: str, *, clock: Clock
    ) -> None:
        self._sessions = sessions
        self._adapter = adapter
        self._clock = clock
        # Two concurrent first uses of a key would otherwise create two remote objects.
        self._lock = asyncio.Lock()

    async def ensure(
        self, kind: ChatBindingKind, local_key: str, create: Callable[[], Awaitable[str]]
    ) -> str:
        """The bound id for `local_key`, calling `create` only when there is none yet."""
        async with self._lock:
            found = await self.external_id(kind, local_key)
            if found is not None:
                return found
            created = await create()
            await self.save(kind, local_key, created)
            return created

    async def bind_thread(self, thread: Thread) -> None:
        await self.save(
            ChatBindingKind.THREAD, thread_key(thread.channel.key, thread.id), thread.id
        )

    async def labhq_thread(self, thread_id: str) -> Thread | None:
        """The thread behind a remote id, if labhq opened it; None for any other channel."""
        key = await self.local_key(ChatBindingKind.THREAD, thread_id)
        if key is None:
            return None
        channel_key = channel_key_of(key)
        channel_id = await self.external_id(ChatBindingKind.CHANNEL, channel_key)
        if channel_id is None:
            return None
        return Thread(Channel(channel_key, channel_id), thread_id)

    async def external_id(self, kind: ChatBindingKind, local_key: str) -> str | None:
        async with self._sessions() as db:
            return await db.scalar(
                select(ChatBinding.external_id).where(
                    ChatBinding.adapter == self._adapter,
                    ChatBinding.kind == kind,
                    ChatBinding.local_key == local_key,
                )
            )

    async def local_key(self, kind: ChatBindingKind, external_id: str) -> str | None:
        async with self._sessions() as db:
            return await db.scalar(
                select(ChatBinding.local_key).where(
                    ChatBinding.adapter == self._adapter,
                    ChatBinding.kind == kind,
                    ChatBinding.external_id == external_id,
                )
            )

    async def save(self, kind: ChatBindingKind, local_key: str, external_id: str) -> None:
        async with self._sessions() as db, db.begin():
            db.add(
                ChatBinding(
                    adapter=self._adapter,
                    kind=kind,
                    local_key=local_key,
                    external_id=external_id,
                    created_at=self._clock.now(),
                )
            )


def thread_key(channel_key: str, thread_id: str) -> str:
    # Threads have no local key of their own; this one also names the channel they live in.
    return f"{channel_key}/{thread_id}"


def channel_key_of(thread_local_key: str) -> str:
    return thread_local_key.rsplit("/", 1)[0]
