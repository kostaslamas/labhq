"""Send to channels: one message to every enabled channel, or one test to a single channel."""

from dataclasses import dataclass
from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.approvals.registry import Registry
from labhq.channels import copy
from labhq.channels.kinds import BuildContext, channel_kinds
from labhq.channels.secrets import read_secrets
from labhq.channels.store import get_channel, list_channels, record_test
from labhq.chat.registry import ChatAdapterFactory, configured_chat_adapters
from labhq.clock import Clock
from labhq.db.models import NotificationChannel
from labhq.notify.base import Message, Notifier, NotifyError
from labhq.notify.settings import NotifySettings

TEST_MESSAGE = Message(copy.TEST_TITLE, copy.TEST_BODY)


@dataclass(frozen=True)
class ChannelRuntime:
    sessions: async_sessionmaker[AsyncSession]
    client: httpx.AsyncClient
    data_dir: Path
    clock: Clock
    settings: NotifySettings
    chat: Registry[ChatAdapterFactory] | None = None

    def notifier_for(self, row: NotificationChannel) -> Notifier:
        context = BuildContext(
            config=row.config,
            secrets=read_secrets(self.data_dir, row.id),
            client=self.client,
            sessions=self.sessions,
            clock=self.clock,
            settings=self.settings,
            data_dir=self.data_dir,
            chat=self.chat if self.chat is not None else configured_chat_adapters(),
        )
        return channel_kinds.get(row.kind).build(context)

    async def test(self, channel_id: int) -> str | None:
        """Send the test message to one channel and store the result; None means it arrived."""
        async with self.sessions() as db:
            row = await get_channel(db, channel_id)
        error = await self._try(row, TEST_MESSAGE)
        async with self.sessions() as db:
            await record_test(db, channel_id, error=error, now=self.clock.now())
            await db.commit()
        return error

    async def _try(self, row: NotificationChannel, message: Message) -> str | None:
        try:
            await self.notifier_for(row).send(message)
        except NotifyError as error:
            return str(error)[:200]
        except Exception as error:
            # Only the type: an unexpected exception's text may carry a URL or credential.
            return type(error).__name__
        return None


class FanOutNotifier:
    """The notifier the dispatcher uses: every enabled channel gets the message.

    With no channel in the database it falls back to the notifier the environment configures,
    so an install that never opened the Channels page keeps notifying as before. A message
    is retried as a whole: a channel that already got it may get it again, which beats a
    channel that never does.
    """

    def __init__(self, runtime: ChannelRuntime, fallback: Notifier) -> None:
        self._runtime = runtime
        self._fallback = fallback

    async def send(self, message: Message) -> None:
        async with self._runtime.sessions() as db:
            rows = await list_channels(db, enabled_only=True)
        if not rows:
            await self._fallback.send(message)
            return
        failed = []
        for row in rows:
            error = await self._runtime._try(row, message)
            if error is not None:
                failed.append(f"{row.name}: {error}")
        if failed:
            raise NotifyError("; ".join(failed))
