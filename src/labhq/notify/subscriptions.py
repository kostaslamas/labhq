"""Stored Web Push subscriptions: the endpoint is the identity, so a re-subscribe replaces."""

from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.db.models import PushSubscription


async def save(db: AsyncSession, now: datetime, *, endpoint: str, p256dh: str, auth: str) -> None:
    row = await db.scalar(select(PushSubscription).where(PushSubscription.endpoint == endpoint))
    if row is None:
        db.add(PushSubscription(endpoint=endpoint, p256dh=p256dh, auth=auth, created_at=now))
        return
    row.p256dh, row.auth = p256dh, auth


async def remove(db: AsyncSession, endpoint: str) -> None:
    await db.execute(delete(PushSubscription).where(PushSubscription.endpoint == endpoint))


async def count(db: AsyncSession) -> int:
    return await db.scalar(select(func.count()).select_from(PushSubscription)) or 0
