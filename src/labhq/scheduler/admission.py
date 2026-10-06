"""Whether the machine can take one more run: a global cap and a free-memory floor.

`dispatch_one` asks here before it queues a run. A refusal leaves the wakeup pending, so
nothing is dropped and the next tick tries again. When memory is short the owner is told
once per episode, not once per tick. The order wakeups are tried in lives here too, so a
capped machine spends its few slots on the owner's messages, then the CEO, then the
managers, then the workers.
"""

import logging
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.ceosessions import CEO_ROLE as CEO
from labhq.clock import Clock
from labhq.db.enums import WakeupSource
from labhq.db.models import Agent, Run, WakeupRequest
from labhq.notify import enqueue as notify
from labhq.scheduler.memory import MemoryMeter, MemoryReading, default_max_running, system_memory
from labhq.scheduler.reaper import LIVE_STATUSES
from labhq.scheduler.settings import SchedulerSettings

log = logging.getLogger(__name__)

OWNER_TO_CEO = 0
CEO_GROUP = 1
MANAGEMENT = 2
WORKERS = 3

# Roles not listed, workers among them, start last. Spelled out here: `labhq.hierarchy`
# imports the scheduler, so its constants cannot be imported back.
ROLE_GROUPS: dict[str, int] = {
    CEO: CEO_GROUP,
    "manager": MANAGEMENT,
    "lead": MANAGEMENT,
    "it": MANAGEMENT,
}


def start_group(source: WakeupSource, role: str) -> int:
    if role == CEO and source is WakeupSource.OWNER_MESSAGE:
        return OWNER_TO_CEO
    return ROLE_GROUPS.get(role, WORKERS)


async def order_by_group(session: AsyncSession, wakeup_ids: list[int]) -> list[int]:
    """`wakeup_ids` regrouped by who may start first; inside a group the order is kept."""
    if not wakeup_ids:
        return []
    rows = await session.execute(
        select(WakeupRequest.id, WakeupRequest.source, Agent.role)
        .join(Agent, Agent.id == WakeupRequest.agent_id)
        .where(WakeupRequest.id.in_(wakeup_ids))
    )
    group = {wakeup_id: start_group(source, role) for wakeup_id, source, role in rows}
    return sorted(wakeup_ids, key=lambda wakeup_id: group.get(wakeup_id, WORKERS))


async def running_count(session: AsyncSession) -> int:
    """Runs holding or about to hold a CLI process, across every agent."""
    count = await session.scalar(
        select(func.count()).select_from(Run).where(Run.status.in_(LIVE_STATUSES))
    )
    return count or 0


class Admission:
    def __init__(
        self,
        settings: SchedulerSettings,
        clock: Clock,
        meter: MemoryMeter = system_memory,
    ) -> None:
        self._settings = settings
        self._clock = clock
        self._meter = meter
        # Start of the current low-memory episode, None while memory is fine.
        self._low_since: datetime | None = None

    def reading(self) -> MemoryReading:
        return self._meter()

    def cap(self, reading: MemoryReading | None = None) -> int:
        if self._settings.max_running is not None:
            return self._settings.max_running
        return default_max_running((reading or self._meter()).total_bytes)

    async def refusal(self, session: AsyncSession) -> str | None:
        """None when one more run may start, else why not: "capacity" or "low_memory"."""
        reading = self._meter()
        if reading.free_percent < self._settings.min_free_memory_percent:
            await self._warn(session, reading)
            return "low_memory"
        self._low_since = None
        if await running_count(session) >= self.cap(reading):
            return "capacity"
        return None

    async def _warn(self, session: AsyncSession, reading: MemoryReading) -> None:
        if self._low_since is not None:
            return
        self._low_since = now = self._clock.now()
        floor = self._settings.min_free_memory_percent
        log.warning(
            "free memory %.1f%% is below %s%%: no new runs start", reading.free_percent, floor
        )
        await notify(
            session,
            kind="server_memory",
            subject="scheduler",
            title=f"Free memory {reading.free_percent:.0f}% is below {floor:g}%",
            body="New agent runs wait, and nothing is dropped, until memory recovers.",
            idempotency_key=f"server-memory-low:{now.isoformat()}",
            now=now,
        )
