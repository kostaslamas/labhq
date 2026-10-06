"""How full the machine is: runs against the cap and the memory left, for the owner to see."""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from labhq.scheduler.admission import running_count
from labhq.scheduler.memory import MemoryMeter, default_max_running, system_memory
from labhq.scheduler.settings import SchedulerSettings, get_scheduler_settings


@dataclass(frozen=True)
class Capacity:
    running: int
    max_running: int
    free_percent: float
    free_bytes: int


async def capacity(
    db: AsyncSession,
    settings: SchedulerSettings | None = None,
    meter: MemoryMeter | None = None,
) -> Capacity:
    settings = settings or get_scheduler_settings()
    reading = (meter or system_memory)()
    cap = settings.max_running or default_max_running(reading.total_bytes)
    return Capacity(await running_count(db), cap, reading.free_percent, reading.available_bytes)
