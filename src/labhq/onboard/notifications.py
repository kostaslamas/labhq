"""Step: one test notification goes through the outbox and the notifier accepts it."""

import asyncio
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import httpx
from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.db import create_engine, session_factory
from labhq.db.enums import NotificationStatus
from labhq.db.models import Notification
from labhq.notify import Dispatcher, NotifyError, NotifySettings, build_notifier, enqueue
from labhq.notify.topic import TOPIC_FILENAME
from labhq.onboard.base import Detection, ManualAction, OnboardContext, Outcome, StepError


@dataclass(frozen=True)
class Channel:
    """What onboarding can say about a notifier kind: its state, and a link to subscribe."""

    describe: Callable[[NotifySettings, Path], str]
    subscribe_link: Callable[[NotifySettings, Path], str | None]


def _ntfy_topic(settings: NotifySettings, data_dir: Path) -> str | None:
    if settings.ntfy_topic:
        return settings.ntfy_topic
    path = data_dir / TOPIC_FILENAME
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8").strip() or None


def _ntfy_describe(settings: NotifySettings, data_dir: Path) -> str:
    topic = "topic kept" if _ntfy_topic(settings, data_dir) else "a new random topic"
    return f"ntfy on {settings.ntfy_server}, {topic}"


def _ntfy_link(settings: NotifySettings, data_dir: Path) -> str | None:
    topic = _ntfy_topic(settings, data_dir)
    return f"{settings.ntfy_server.rstrip('/')}/{topic}" if topic else None


# Keyed like `labhq.notify.notifiers`; a kind without a row still sends, it just has no link.
CHANNELS: dict[str, Channel] = {
    "ntfy": Channel(_ntfy_describe, _ntfy_link),
    "telegram": Channel(lambda settings, data_dir: "Telegram bot", lambda *_: None),
}


class NotificationsStep:
    name = "notifications"
    required = True

    def detect(self, context: OnboardContext) -> Detection:
        settings = NotifySettings()
        channel = CHANNELS.get(settings.kind)
        detail = channel.describe(settings, context.settings.data_dir) if channel else settings.kind
        return Detection(True, detail)

    def manual(self, context: OnboardContext, detection: Detection) -> ManualAction | None:
        return None

    def automate(self, context: OnboardContext) -> None:
        """Nothing up front: the notifier creates and keeps its own topic on first use."""

    def verify(self, context: OnboardContext) -> Outcome:
        settings = NotifySettings()
        try:
            error = asyncio.run(self._send_test(context, settings))
        except SQLAlchemyError as failure:
            raise StepError(f"cannot use the outbox: {failure}") from failure
        if error is not None:
            raise StepError(f"the test notification was not accepted ({error})")
        channel = CHANNELS.get(settings.kind)
        link = channel.subscribe_link(settings, context.settings.data_dir) if channel else None
        return Outcome(
            f"{settings.kind} accepted a test notification",
            label=f"Subscribe in the {settings.kind} app" if link else None,
            link=link,
            qr=True,
        )

    @staticmethod
    async def _send_test(context: OnboardContext, settings: NotifySettings) -> str | None:
        """Returns None once sent, else the reason; a failed row is not retried later."""
        engine = create_engine(context.settings.resolved_database_url)
        sessions = session_factory(engine)
        try:
            async with httpx.AsyncClient(timeout=context.onboard.http_timeout_seconds) as client:
                try:
                    notifier = build_notifier(settings, client, context.settings.data_dir)
                except NotifyError as error:
                    return str(error)
                row_id = await _enqueue_test(sessions, context.clock.now())
                dispatcher = Dispatcher(sessions, notifier, clock=context.clock, settings=settings)
                await dispatcher.dispatch_pending()
            async with sessions() as db:
                sent = await db.get(Notification, row_id)
                assert sent is not None
                if sent.status == NotificationStatus.SENT:
                    return None
                reason = sent.last_error or "not sent"
                await db.execute(
                    update(Notification)
                    .where(Notification.id == row_id)
                    .values(status=NotificationStatus.FAILED, next_attempt_at=None)
                )
                await db.commit()
                return reason
        finally:
            await engine.dispose()


async def _enqueue_test(sessions: async_sessionmaker[AsyncSession], now: datetime) -> int:
    async with sessions() as db:
        row = await enqueue(
            db,
            kind="onboard",
            subject="onboard",
            title="labhq is set up",
            body="Notifications from labhq reach this device.",
            # Random, so a second run sends a fresh check instead of finding the first.
            idempotency_key=f"onboard:{secrets.token_hex(8)}",
            now=now,
        )
        await db.commit()
        return row.id
