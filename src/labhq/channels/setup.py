"""Add a channel, prove it with a test message, and let the Call Center confirm it is live."""

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.channels import copy
from labhq.channels.runtime import ChannelRuntime
from labhq.channels.store import add_channel, get_channel
from labhq.clock import Clock
from labhq.db.models import CeoReport, NotificationChannel

REPORT_REF = "channel:{name}"


async def create_and_test(
    sessions: async_sessionmaker[AsyncSession],
    runtime: ChannelRuntime,
    data_dir: Path,
    clock: Clock,
    *,
    kind: str,
    name: str,
    values: dict[str, str],
) -> tuple[NotificationChannel, str | None]:
    """Create the channel, send its test message and, when it arrives, tell the CEO.

    Returns the stored channel and the test's failure reason (None: it arrived). A channel
    whose test fails stays, disabled-by-failure in the list, so the owner can fix or remove it.
    """
    async with sessions() as db:
        row = await add_channel(db, data_dir, kind=kind, name=name, values=values, now=clock.now())
        await db.commit()
        channel_id = row.id
    error = await runtime.test(channel_id)
    async with sessions() as db:
        row = await get_channel(db, channel_id)
        if error is None:
            db.add(
                CeoReport(
                    agent_id=None,
                    text=copy.CHANNEL_LIVE.format(name=row.name, kind=row.kind),
                    refs=[REPORT_REF.format(name=row.name)],
                    task_id=None,
                    created_at=clock.now(),
                )
            )
            await db.commit()
        return row, error
