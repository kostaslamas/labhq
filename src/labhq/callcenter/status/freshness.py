"""Fresh or stale is a mechanical rule (ADR 0004).

A status is fresh when it is newer than the agent's last activity: the later of its latest
`run_events` row and its last screen change. Given a screen reader, the agent's pane is
captured, read-only, to see that change; the captured screen comes back with the answer, so
a stale status can be answered from the screen. An agent with no pane (an SDK run, an ended
run) is judged on its events alone, and a stale status is reported as stale, with its age.
"""

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.callcenter.screens import Screen, ScreenReader
from labhq.clock import Clock
from labhq.db.models import Run, RunEvent, StatusUpdate


@dataclass(frozen=True)
class Freshness:
    update: StatusUpdate | None
    fresh: bool
    # How long ago the status was written; None when the agent never reported.
    age: timedelta | None
    # The agent's screen, when it runs in tmux and a reader was given.
    screen: Screen | None = None


async def status_freshness(
    db: AsyncSession,
    clock: Clock,
    agent_id: int,
    task_id: int | None = None,
    screens: ScreenReader | None = None,
) -> Freshness:
    """The agent's latest status (for `task_id` when given) and whether it is fresh."""
    query = select(StatusUpdate).where(StatusUpdate.agent_id == agent_id)
    if task_id is not None:
        query = query.where(StatusUpdate.task_id == task_id)
    update = await db.scalar(query.order_by(StatusUpdate.observed_at.desc()).limit(1))
    screen = await screens.capture(db, clock, agent_id=agent_id) if screens else None
    if update is None:
        return Freshness(None, False, None, screen)
    last_event = await db.scalar(
        select(func.max(RunEvent.created_at))
        .join(Run, Run.id == RunEvent.run_id)
        .where(Run.agent_id == agent_id)
    )
    activity = [moment for moment in (last_event, screen and screen.changed_at) if moment]
    fresh = not activity or update.observed_at > max(activity)
    return Freshness(update, fresh, clock.now() - update.observed_at, screen)
