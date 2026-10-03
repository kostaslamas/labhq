"""Send pending outbox rows once, retrying failures with exponential backoff.

A row is claimed with a conditional UPDATE that also pushes `next_attempt_at` out by a lease,
so two dispatchers never send the same row and a crash mid-send retries after the lease.
"""

from datetime import timedelta
from typing import cast

from sqlalchemy import CursorResult, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.clock import Clock
from labhq.db.enums import NotificationStatus
from labhq.db.models import Notification
from labhq.notify.base import Message, Notifier, NotifyError
from labhq.notify.settings import NotifySettings


class Dispatcher:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        notifier: Notifier,
        *,
        clock: Clock,
        settings: NotifySettings,
    ) -> None:
        self._sessions = sessions
        self._notifier = notifier
        self._clock = clock
        self._settings = settings

    async def dispatch_pending(self) -> int:
        """Try every due row once; return how many were sent."""
        now = self._clock.now()
        async with self._sessions() as db:
            due = await db.execute(
                select(Notification.id, Notification.attempts)
                .where(
                    Notification.status == NotificationStatus.PENDING,
                    or_(
                        Notification.next_attempt_at.is_(None),
                        Notification.next_attempt_at <= now,
                    ),
                )
                .order_by(Notification.id)
            )
            targets = [(row_id, attempts) for row_id, attempts in due]
        sent = 0
        for row_id, attempts in targets:
            if await self._deliver(row_id, attempts):
                sent += 1
        return sent

    async def _claim(self, row_id: int, seen_attempts: int) -> Message | None:
        lease = self._clock.now() + timedelta(seconds=self._settings.claim_lease_seconds)
        async with self._sessions() as db:
            claim = await db.execute(
                update(Notification)
                .where(
                    Notification.id == row_id,
                    Notification.status == NotificationStatus.PENDING,
                    Notification.attempts == seen_attempts,
                )
                .values(attempts=seen_attempts + 1, next_attempt_at=lease)
            )
            if cast(CursorResult[object], claim).rowcount != 1:
                return None
            row = await db.get(Notification, row_id)
            assert row is not None
            message = Message(row.title, row.body, row.click_url)
            await db.commit()
        return message

    async def _deliver(self, row_id: int, seen_attempts: int) -> bool:
        message = await self._claim(row_id, seen_attempts)
        if message is None:
            return False
        try:
            await self._notifier.send(message)
        except NotifyError as error:
            await self._record_failure(row_id, seen_attempts + 1, str(error))
            return False
        except Exception as error:
            # Only the type: an unexpected exception's text may carry a URL or credential.
            await self._record_failure(row_id, seen_attempts + 1, type(error).__name__)
            return False
        async with self._sessions() as db:
            await db.execute(
                update(Notification)
                .where(Notification.id == row_id)
                .values(
                    status=NotificationStatus.SENT,
                    sent_at=self._clock.now(),
                    next_attempt_at=None,
                    last_error=None,
                )
            )
            await db.commit()
        return True

    async def _record_failure(self, row_id: int, attempts: int, error: str) -> None:
        settings = self._settings
        if attempts >= settings.max_attempts:
            status, next_attempt = NotificationStatus.FAILED, None
        else:
            delay = min(
                settings.backoff_base_seconds * 2 ** (attempts - 1), settings.backoff_max_seconds
            )
            status = NotificationStatus.PENDING
            next_attempt = self._clock.now() + timedelta(seconds=delay)
        async with self._sessions() as db:
            await db.execute(
                update(Notification)
                .where(Notification.id == row_id)
                .values(status=status, next_attempt_at=next_attempt, last_error=error[:500])
            )
            await db.commit()
