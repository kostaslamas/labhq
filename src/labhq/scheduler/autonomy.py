"""Wakeups the global autonomy switch holds back while it is paused.

Held wakeups stay pending and start on the first tick after the owner turns autonomy on.
Only sources named in `OWNER_DRIVEN` get through: the owner's own message is a conversation,
not the organisation acting on its own.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.autonomy.settings import Autonomy, AutonomySettings
from labhq.autonomy.state import get_autonomy
from labhq.db.enums import WakeupSource, WakeupStatus
from labhq.db.models import WakeupRequest

OWNER_DRIVEN = frozenset({WakeupSource.OWNER_MESSAGE})


async def held_wakeup_ids(db: AsyncSession, settings: AutonomySettings | None) -> set[int]:
    if await get_autonomy(db, settings) is Autonomy.ON:
        return set()
    held = await db.scalars(
        select(WakeupRequest.id).where(
            WakeupRequest.status == WakeupStatus.PENDING,
            WakeupRequest.source.not_in(OWNER_DRIVEN),
        )
    )
    return set(held)
