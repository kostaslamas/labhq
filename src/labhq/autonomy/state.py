"""The global autonomy switch: the database row if the owner set one, else the environment."""

from sqlalchemy.ext.asyncio import AsyncSession

from labhq.autonomy.settings import Autonomy, AutonomySettings, get_autonomy_settings
from labhq.clock import Clock
from labhq.db.models import ProgramState

KEY = "autonomy"


async def get_autonomy(db: AsyncSession, settings: AutonomySettings | None = None) -> Autonomy:
    row = await db.get(ProgramState, KEY, populate_existing=True)
    if row is None:
        return (settings or get_autonomy_settings()).autonomy
    return Autonomy(row.value)


async def set_autonomy(db: AsyncSession, clock: Clock, value: Autonomy) -> Autonomy:
    row = await db.get(ProgramState, KEY)
    if row is None:
        db.add(ProgramState(key=KEY, value=value.value, updated_at=clock.now()))
    else:
        row.value = value.value
        row.updated_at = clock.now()
    await db.commit()
    return value
