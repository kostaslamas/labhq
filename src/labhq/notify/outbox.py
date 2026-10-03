"""Write side of the outbox: a row in the caller's transaction, sent later by the dispatcher."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.db.enums import NotificationStatus
from labhq.db.models import Notification


async def enqueue(
    db: AsyncSession,
    *,
    kind: str,
    subject: str,
    title: str,
    body: str,
    idempotency_key: str,
    click_url: str | None = None,
    now: datetime,
) -> Notification:
    """Insert a pending row, or return the existing one for a repeated key.

    The caller commits, so the row lands in the same transaction as the event it announces.
    """
    existing = await _by_key(db, idempotency_key)
    if existing is not None:
        return existing
    row = Notification(
        kind=kind,
        subject=subject,
        title=title,
        body=body,
        click_url=click_url,
        status=NotificationStatus.PENDING,
        attempts=0,
        idempotency_key=idempotency_key,
        created_at=now,
    )
    try:
        # A savepoint, so losing a race on the unique key does not abort the caller's transaction.
        async with db.begin_nested():
            db.add(row)
    except IntegrityError:
        raced = await _by_key(db, idempotency_key)
        if raced is None:
            raise
        return raced
    return row


async def _by_key(db: AsyncSession, key: str) -> Notification | None:
    return await db.scalar(select(Notification).where(Notification.idempotency_key == key))
