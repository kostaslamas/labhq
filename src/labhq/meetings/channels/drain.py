"""Send pending posts in id order through one chat adapter.

A failure stops the pass, so nothing overtakes the post that failed: the backlog arrives in
the order it was written once the adapter is back. The failed post waits with a doubling
backoff, capped, and is never dropped.
"""

import logging
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.chat import Channel, ChatAdapter, Persona, Thread
from labhq.clock import Clock
from labhq.db.models import Meeting
from labhq.meetings.channels.models import ChatPost, ChatPostStatus
from labhq.meetings.channels.settings import ChannelSettings

logger = logging.getLogger(__name__)

ERROR_LENGTH = 500


class OutboxDrain:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        clock: Clock,
        settings: ChannelSettings,
    ) -> None:
        self._sessions = sessions
        self._clock = clock
        self._settings = settings

    async def drain(self, name: str, adapter: ChatAdapter) -> int:
        """Send what is due; returns how many posts went out."""
        async with self._sessions() as db:
            pending = list(
                await db.scalars(
                    select(ChatPost.id)
                    .where(ChatPost.status == ChatPostStatus.PENDING)
                    .order_by(ChatPost.id)
                    .limit(self._settings.batch_size)
                )
            )
        sent = 0
        for post_id in pending:
            async with self._sessions() as db:
                post = await db.get_one(ChatPost, post_id)
                due = post.next_attempt_at
            if due is not None and due > self._clock.now():
                break
            try:
                await self._send(name, adapter, post)
            except Exception as error:
                # Any adapter failure (refusal, network, a closed gateway) is a reason to wait.
                await self._failed(post, error)
                break
            sent += 1
        return sent

    async def _send(self, name: str, adapter: ChatAdapter, post: ChatPost) -> None:
        channel = await adapter.ensure_channel(post.channel_key, post.channel_name)
        thread = await self._thread(name, adapter, channel, post)
        await adapter.post(thread, Persona(post.persona_name, post.avatar_url), post.text)
        async with self._sessions() as db:
            await db.execute(
                update(ChatPost)
                .where(ChatPost.id == post.id)
                .values(
                    status=ChatPostStatus.SENT,
                    adapter=name,
                    thread_ref=thread.id,
                    sent_at=self._clock.now(),
                    last_error=None,
                )
            )
            await db.commit()

    async def _thread(
        self, name: str, adapter: ChatAdapter, channel: Channel, post: ChatPost
    ) -> Thread:
        async with self._sessions() as db:
            known = await db.scalar(
                select(ChatPost.thread_ref)
                .where(
                    ChatPost.thread_key == post.thread_key,
                    ChatPost.adapter == name,
                    ChatPost.thread_ref.is_not(None),
                )
                .limit(1)
            )
        if known is not None:
            return Thread(channel, known)
        thread = await adapter.open_thread(channel, post.thread_title)
        # Kept before the post is attempted: a retry after a failed post reuses this thread
        # instead of opening a second one.
        async with self._sessions() as db:
            await db.execute(
                update(ChatPost)
                .where(ChatPost.id == post.id)
                .values(adapter=name, thread_ref=thread.id)
            )
            if post.meeting_id is not None:
                await db.execute(
                    update(Meeting)
                    .where(Meeting.id == post.meeting_id)
                    .values(channel_adapter=name, external_ref=thread.id)
                )
            await db.commit()
        return thread

    async def _failed(self, post: ChatPost, error: Exception) -> None:
        attempts = post.attempts + 1
        delay = min(
            self._settings.retry_base_seconds * 2 ** (attempts - 1),
            self._settings.retry_max_seconds,
        )
        logger.warning(
            "chat post %s failed (attempt %s), retrying in %ss: %s",
            post.id,
            attempts,
            delay,
            type(error).__name__,
        )
        async with self._sessions() as db:
            await db.execute(
                update(ChatPost)
                .where(ChatPost.id == post.id)
                .values(
                    attempts=attempts,
                    next_attempt_at=self._clock.now() + timedelta(seconds=delay),
                    last_error=f"{type(error).__name__}: {error}"[:ERROR_LENGTH],
                )
            )
            await db.commit()
