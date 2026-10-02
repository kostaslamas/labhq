"""Finding runs to stop, and closing a run with its checkout released.

The queries only read; `close_run` is the single place a scheduler-side stop writes a
terminal status. Its update is conditional on the run still being active, so a run that
finished on its own in the meantime keeps the status it reported.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.db.enums import RunStatus
from labhq.db.models import Agent, Run
from labhq.scheduler.checkout import ACTIVE_RUN_STATUSES, release
from labhq.scheduler.settings import SchedulerSettings, limits_for


@dataclass(frozen=True, slots=True)
class RunToStop:
    run_id: int
    task_id: int | None
    exit: dict[str, Any]


async def stale_runs(
    session: AsyncSession, now: datetime, settings: SchedulerSettings
) -> list[RunToStop]:
    """Active runs whose last heartbeat is older than the limit (plan §7, rule 5)."""
    cutoff = now - settings.heartbeat_limit
    # A run that never beat counts from its creation.
    last_seen = func.coalesce(Run.heartbeat_at, Run.created_at)
    rows = await session.execute(
        select(Run.id, Run.task_id, Run.heartbeat_at, Run.created_at).where(
            Run.status.in_(ACTIVE_RUN_STATUSES), last_seen < cutoff
        )
    )
    return [
        RunToStop(
            run_id,
            task_id,
            {
                "error": "stale_heartbeat",
                "heartbeat_at": (heartbeat_at or created_at).isoformat(),
                "heartbeat_limit_seconds": settings.heartbeat_limit_seconds,
            },
        )
        for run_id, task_id, heartbeat_at, created_at in rows
    ]


async def overdue_runs(
    session: AsyncSession, now: datetime, settings: SchedulerSettings
) -> list[RunToStop]:
    """Running runs past the timeout their agent's config sets (plan §7, rule 6)."""
    rows = await session.execute(
        select(Run.id, Run.task_id, Run.started_at, Agent.config)
        .join(Agent, Agent.id == Run.agent_id)
        .where(Run.status == RunStatus.RUNNING, Run.started_at.is_not(None))
    )
    overdue = []
    for run_id, task_id, started_at, config in rows:
        timeout = limits_for(config, settings).timeout
        if started_at + timeout <= now:
            exit = {"error": "timeout", "timeout_seconds": int(timeout.total_seconds())}
            overdue.append(RunToStop(run_id, task_id, exit))
    return overdue


async def close_run(
    session: AsyncSession, target: RunToStop, status: RunStatus, now: datetime
) -> bool:
    """End an active run as `status` and release its checkout. False if it had ended."""
    run = await session.get(Run, target.run_id)
    exit = {**(run.exit or {}), **target.exit} if run is not None else target.exit
    result = await session.execute(
        update(Run)
        .where(Run.id == target.run_id, Run.status.in_(ACTIVE_RUN_STATUSES))
        .values(status=status, exit=exit, finished_at=now, heartbeat_at=now)
        .execution_options(synchronize_session=False)
    )
    if target.task_id is not None:
        await release(session, target.task_id, target.run_id, now)
    return bool(result.rowcount)  # type: ignore[attr-defined]


async def relabel_interrupted(
    session: AsyncSession, target: RunToStop, status: RunStatus, now: datetime
) -> None:
    """Relabel a run the scheduler interrupted, e.g. as timed out, and release its task.

    A run that finished some other way before the interrupt landed keeps its status.
    """
    run = await session.get_one(Run, target.run_id)
    if run.status is RunStatus.INTERRUPTED:
        run.status = status
        run.exit = {**(run.exit or {}), **target.exit}
        run.finished_at = run.finished_at or now
    if target.task_id is not None:
        await release(session, target.task_id, target.run_id, now)
