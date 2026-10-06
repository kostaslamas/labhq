"""`GET /api/capacity`."""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select

from labhq.api.deps import SessionDep
from labhq.db.enums import WakeupStatus
from labhq.db.models import WakeupRequest
from labhq.scheduler.capacity import capacity
from labhq.scheduler.memory import MemoryMeter, system_memory
from labhq.scheduler.settings import SchedulerSettings, get_scheduler_settings

router = APIRouter(prefix="/capacity", tags=["capacity"])


class RunCapacity(BaseModel):
    running: int
    max_running: int
    free_memory_percent: float
    min_free_memory_percent: float
    # True while the free-memory floor keeps new runs from starting.
    paused_for_memory: bool
    # Pending wakeups held back by the cap or the memory floor right now; 0 while neither bites.
    waiting: int


# Dependencies, so a test or the e2e server injects readings instead of reading the machine.
def get_meter() -> MemoryMeter:
    return system_memory


def get_settings() -> SchedulerSettings:
    return get_scheduler_settings()


@router.get("")
async def capacity_get(
    db: SessionDep,
    meter: Annotated[MemoryMeter, Depends(get_meter)],
    settings: Annotated[SchedulerSettings, Depends(get_settings)],
) -> RunCapacity:
    """Runs against the global cap, free memory against its floor, and what waits for them."""
    now = await capacity(db, settings, meter)
    floor = settings.min_free_memory_percent
    paused = now.free_percent < floor
    blocked = paused or now.running >= now.max_running
    waiting = 0
    if blocked:
        waiting = (
            await db.scalar(
                select(func.count())
                .select_from(WakeupRequest)
                .where(WakeupRequest.status == WakeupStatus.PENDING)
            )
            or 0
        )
    return RunCapacity(
        running=now.running,
        max_running=now.max_running,
        free_memory_percent=round(now.free_percent, 1),
        min_free_memory_percent=floor,
        paused_for_memory=paused,
        waiting=waiting,
    )
