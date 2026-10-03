"""Capture a working agent's pane on labhq's private tmux server, and nothing more.

The reader holds a `PaneSource`, whose only method is `capture`: there is no path from here
to `send-keys`, so reading a screen can never type into an agent that works (ADR 0004).
Only a run that is running on the `tmux` adapter has a pane; an SDK run or an ended one has
none, and its agent is reported from its status alone.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.adapters.tmux import TmuxError, TmuxMissingError, TmuxServer, get_tmux_settings
from labhq.adapters.tmux.adapter import session_name
from labhq.callcenter.screens.log import ScreenLog
from labhq.clock import Clock
from labhq.db.enums import RunStatus
from labhq.db.models import Run, RunEvent
from labhq.settings import get_settings

TMUX_ADAPTER = "tmux"
SCREENS_DIR = "screens"
# What the Call Center reads: the bottom of the screen, where the agent's latest work is.
TAIL_LINES = 40
TAIL_CHARS = 4000


class PaneSource(Protocol):
    def capture(self, name: str) -> str: ...


@dataclass(frozen=True)
class Screen:
    run_id: int
    agent_id: int
    text: str
    changed_at: datetime


def screen_tail(text: str, lines: int = TAIL_LINES, chars: int = TAIL_CHARS) -> str:
    tail = "\n".join(text.splitlines()[-lines:])
    return tail[-chars:]


async def running_tmux_run(
    db: AsyncSession, *, agent_id: int | None = None, task_id: int | None = None
) -> Run | None:
    """The latest running tmux run of the agent, or on the task."""
    query = select(Run).where(Run.status == RunStatus.RUNNING, Run.adapter == TMUX_ADAPTER)
    if agent_id is not None:
        query = query.where(Run.agent_id == agent_id)
    if task_id is not None:
        query = query.where(Run.task_id == task_id)
    return await db.scalar(query.order_by(Run.id.desc()).limit(1))


async def _last_event_at(db: AsyncSession, run_id: int) -> datetime | None:
    return await db.scalar(select(func.max(RunEvent.created_at)).where(RunEvent.run_id == run_id))


class ScreenReader:
    def __init__(self, panes: PaneSource, log: ScreenLog) -> None:
        self._panes = panes
        self._log = log

    async def capture(
        self,
        db: AsyncSession,
        clock: Clock,
        *,
        agent_id: int | None = None,
        task_id: int | None = None,
    ) -> Screen | None:
        """The screen of the agent's (or task's) running tmux run; None when there is none."""
        run = await running_tmux_run(db, agent_id=agent_id, task_id=task_id)
        if run is None:
            return None
        try:
            text = await asyncio.to_thread(self._panes.capture, session_name(run.id))
        except TmuxError:
            # The run ended between the query and the capture, or its server is gone.
            return None
        now = clock.now()
        first_seen = await _last_event_at(db, run.id) or run.started_at or now
        changed_at = self._log.observe(run.id, text, now, first_seen)
        return Screen(run_id=run.id, agent_id=run.agent_id, text=text, changed_at=changed_at)


def default_screen_reader() -> ScreenReader | None:
    """A reader on labhq's private server, or None where tmux is not installed."""
    state_dir = get_settings().data_dir / TMUX_ADAPTER
    try:
        server = TmuxServer(socket=get_tmux_settings().socket, state_dir=state_dir)
    except TmuxMissingError:
        return None
    return ScreenReader(server, ScreenLog(state_dir / SCREENS_DIR))
