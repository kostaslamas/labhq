"""Whether a running agent is working, waiting for the owner, or idle: no model, no transcript.

Working: its CPU time moved during a short sample, or it has child processes (a tool runs).
Waiting: quiet, and the bottom of its tmux pane matches one of the dialogs its kind is known
to stop on (`blocking_screens`). The pane text is matched and dropped, never stored. Idle:
quiet and not at a dialog.
"""

import time
from collections.abc import Callable, Sequence
from typing import Protocol

import psutil

from labhq.adapters.tmux import AgentKinds
from labhq.adapters.tmux.blocking import blocking_screen
from labhq.adoption.discovery import RunningAgent
from labhq.adoption.observe import OwnerTmux
from labhq.inventory.model import SessionState
from labhq.inventory.settings import InventorySettings

Sleep = Callable[[float], None]


class Probe(Protocol):
    def states(self, agents: Sequence[RunningAgent]) -> dict[int, SessionState]: ...


class ProcessProbe:
    def __init__(
        self,
        kinds: AgentKinds,
        settings: InventorySettings,
        tmux: OwnerTmux | None = None,
        sleep: Sleep = time.sleep,
    ) -> None:
        self._kinds = kinds
        self._settings = settings
        self._tmux = tmux
        self._sleep = sleep

    def states(self, agents: Sequence[RunningAgent]) -> dict[int, SessionState]:
        before = {a.pid: _cpu(a.pid) for a in agents}
        self._sleep(self._settings.sample_seconds)
        result: dict[int, SessionState] = {}
        for agent in agents:
            if self._working(agent, before[agent.pid]):
                result[agent.pid] = SessionState.RUNNING
            elif self._at_dialog(agent):
                result[agent.pid] = SessionState.WAITING
            else:
                result[agent.pid] = SessionState.IDLE
        return result

    def _working(self, agent: RunningAgent, before: float | None) -> bool:
        after = _cpu(agent.pid)
        if before is None or after is None:
            return False
        moved = after - before > self._settings.busy_cpu_seconds
        return moved or _has_children(agent.pid)

    def _at_dialog(self, agent: RunningAgent) -> bool:
        if self._tmux is None:
            return False
        pane = self._tmux.pane_of(agent.pid)
        screen = self._tmux.capture(pane) if pane else None
        if not screen:
            return False
        return blocking_screen(self._kinds.get(agent.kind).blocking_screens, screen) is not None


def _cpu(pid: int) -> float | None:
    try:
        times = psutil.Process(pid).cpu_times()
    except psutil.Error:
        return None
    return times.user + times.system


def _has_children(pid: int) -> bool:
    try:
        return bool(psutil.Process(pid).children())
    except psutil.Error:
        return False
