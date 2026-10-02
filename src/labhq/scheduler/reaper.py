"""Stale-run reaper: a run with no sign of life within the limit has lost its owner.

Its last sign of life is its heartbeat, or its creation for a run queued but never
started. It closes as `failed` and gives its task back. Each close is a conditional UPDATE
on the status and instant it read, so a run that beats or finishes meanwhile is left alone.
"""

from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.clock import Clock
from labhq.db.enums import RunStatus
from labhq.db.models import Run
from labhq.scheduler.checkout import release

STALE_ERROR = "stale_heartbeat"
LIVE_STATUSES = (RunStatus.QUEUED, RunStatus.RUNNING)

_last_seen = func.coalesce(Run.heartbeat_at, Run.created_at)


async def reap_stale_runs(session: AsyncSession, clock: Clock, limit: timedelta) -> list[int]:
    """Close every stale run and release its checkout. Returns the reaped run ids.

    Flushes but never commits: the caller owns the transaction.
    """
    now = clock.now()
    stale = (
        await session.execute(
            select(Run.id, Run.status, _last_seen).where(
                Run.status.in_(LIVE_STATUSES), _last_seen < now - limit
            )
        )
    ).all()
    reaped: list[int] = []
    for run_id, status, last_seen in stale:
        if await _close(session, run_id, status, last_seen, now, limit):
            await release(session, run_id)
            reaped.append(run_id)
    return reaped


async def _close(
    session: AsyncSession,
    run_id: int,
    status: RunStatus,
    last_seen: datetime,
    now: datetime,
    limit: timedelta,
) -> bool:
    result = await session.execute(
        update(Run)
        .where(Run.id == run_id, Run.status == status, _last_seen == last_seen)
        .values(
            status=RunStatus.FAILED,
            finished_at=now,
            exit={
                "error": STALE_ERROR,
                "message": f"no sign of life since {last_seen.isoformat()}",
                "limit_seconds": int(limit.total_seconds()),
            },
        )
        .execution_options(synchronize_session=False)
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]
