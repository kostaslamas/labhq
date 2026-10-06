"""Stop the CLI of a persistent pane that has been idle too long, keeping its session.

Each CEO CLI stays alive in its tmux pane between turns and holds hundreds of MB while
doing nothing. Past the idle limit its process is stopped; the tmux session and the
conversation id survive, so the next turn finds a dead pane, respawns it with the CLI's
resume command and carries on (`TmuxAdapter.start`).
"""

import asyncio
import logging
import os
import signal
from datetime import datetime, timedelta

from labhq.adapters.tmux.adapter import IDLE_FILE
from labhq.adapters.tmux.server import TmuxError, TmuxServer
from labhq.clock import Clock

log = logging.getLogger(__name__)

# Listing sessions costs a subprocess; the idle limit is minutes, so a tick need not.
CHECK_EVERY = timedelta(seconds=60)


class IdleSuspender:
    def __init__(
        self,
        server: TmuxServer,
        clock: Clock,
        *,
        idle_seconds: int,
        check_every: timedelta = CHECK_EVERY,
    ) -> None:
        self._server = server
        self._clock = clock
        self._idle = timedelta(seconds=idle_seconds)
        self._check_every = check_every
        self._checked_at: datetime | None = None

    async def suspend_idle(self) -> list[str]:
        """Stop every pane idle past the limit; return the session names it stopped."""
        if self._idle <= timedelta(0):
            return []
        now = self._clock.now()
        if self._checked_at is not None and now - self._checked_at < self._check_every:
            return []
        self._checked_at = now
        return await asyncio.to_thread(self._suspend, now)

    def _suspend(self, now: datetime) -> list[str]:
        stopped: list[str] = []
        try:
            names = self._server.list_sessions()
        except TmuxError:
            # No server yet: nothing has run, so nothing is idle.
            return stopped
        for name in names:
            marker = self._server.state_dir / "runs" / name / IDLE_FILE
            try:
                since = datetime.fromisoformat(marker.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if now - since < self._idle:
                continue
            try:
                if self._stop(name):
                    stopped.append(name)
            except (TmuxError, OSError):
                log.exception("could not stop the idle pane %s", name)
        return stopped

    def _stop(self, name: str) -> bool:
        if self._server.pane_state(name).dead:
            return False
        pid = self._server.pane_pid(name)
        if pid is None:
            return False
        os.kill(pid, signal.SIGTERM)
        return True
