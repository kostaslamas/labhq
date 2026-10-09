"""Channels in the database; their secrets in the data directory (`labhq.channels.secrets`)."""

import contextlib
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.approvals.registry import UnknownEntryError
from labhq.channels.kinds import ChannelConfigError, channel_kinds
from labhq.channels.secrets import delete_secrets, write_secrets
from labhq.db.models import NotificationChannel


class ChannelNotFoundError(LookupError):
    pass


async def list_channels(
    db: AsyncSession, *, enabled_only: bool = False
) -> list[NotificationChannel]:
    query = select(NotificationChannel).order_by(NotificationChannel.id)
    if enabled_only:
        query = query.where(NotificationChannel.enabled.is_(True))
    return list(await db.scalars(query))


async def get_channel(db: AsyncSession, channel_id: int) -> NotificationChannel:
    row = await db.get(NotificationChannel, channel_id)
    if row is None:
        raise ChannelNotFoundError(f"no channel {channel_id}")
    return row


async def add_channel(
    db: AsyncSession,
    data_dir: Path,
    *,
    kind: str,
    name: str,
    values: dict[str, str],
    now: datetime,
) -> NotificationChannel:
    """Create a channel; the caller commits. Raises `ChannelConfigError` for bad input."""
    try:
        definition = channel_kinds.get(kind)
    except UnknownEntryError:
        raise ChannelConfigError(f"unknown channel kind {kind!r}") from None
    name = name.strip()
    if not name or len(name) > 64:
        raise ChannelConfigError("a channel needs a name of up to 64 characters")
    config, secrets = definition.split(values)
    row = NotificationChannel(kind=kind, name=name, config=config, enabled=True, created_at=now)
    try:
        async with db.begin_nested():
            db.add(row)
    except IntegrityError:
        raise ChannelConfigError(f"a channel named {name!r} already exists") from None
    write_secrets(data_dir, row.id, secrets)
    return row


async def remove_channel(db: AsyncSession, data_dir: Path, channel_id: int) -> None:
    row = await get_channel(db, channel_id)
    await db.delete(row)
    await db.flush()
    # After the row: a failed delete never strands a channel without its secret.
    with contextlib.suppress(OSError):
        delete_secrets(data_dir, channel_id)


async def set_enabled(db: AsyncSession, channel_id: int, enabled: bool) -> NotificationChannel:
    row = await get_channel(db, channel_id)
    row.enabled = enabled
    await db.flush()
    return row


async def record_test(
    db: AsyncSession, channel_id: int, *, error: str | None, now: datetime
) -> NotificationChannel:
    row = await get_channel(db, channel_id)
    row.last_test_ok = error is None
    row.last_test_error = error
    row.last_tested_at = now
    await db.flush()
    return row
