"""Fresh or stale is a mechanical rule (ADR 0004).

A status is fresh when it is newer than the agent's latest `run_events` row. Reading a
pane when it is stale waits for the tmux adapter; until then a stale status is reported as
stale, with its age.
"""

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.clock import Clock
from labhq.db.models import Run, RunEvent, StatusUpdate


@dataclass(frozen=True)
class Freshness:
    update: StatusUpdate | None
    fresh: bool
    # How long ago the status was written; None when the agent never reported.
    age: timedelta | None


async def status_freshness(
    db: AsyncSession, clock: Clock, agent_id: int, task_id: int | None = None
) -> Freshness:
    """The agent's latest status (for `task_id` when given) and whether it is fresh."""
    query = select(StatusUpdate).where(StatusUpdate.agent_id == agent_id)
    if task_id is not None:
        query = query.where(StatusUpdate.task_id == task_id)
    update = await db.scalar(query.order_by(StatusUpdate.observed_at.desc()).limit(1))
    if update is None:
        return Freshness(None, False, None)
    last_activity = await db.scalar(
        select(func.max(RunEvent.created_at))
        .join(Run, Run.id == RunEvent.run_id)
        .where(Run.agent_id == agent_id)
    )
    fresh = last_activity is None or update.observed_at > last_activity
    return Freshness(update, fresh, clock.now() - update.observed_at)
