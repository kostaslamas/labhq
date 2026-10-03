"""Watch the agent to adopt, read-only, until its turn ends (ADR 0005, "Observe").

In the owner's tmux, labhq captures the agent's pane, so the Call Center can answer about
it. In any other terminal there is no screen to read; the process's CPU time and child
processes stand in for it. Either way labhq sends the agent no keys: an observer has no
method that could.
"""

import hashlib
import os
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

import psutil

from labhq.adapters.tmux.environment import client_environment
from labhq.adoption.discovery import is_alive
from labhq.clock import Clock

# Where the owner's default tmux server keeps its socket, besides the allowlist.
OWNER_TMUX_VARIABLES = ("TMUX_TMPDIR",)


class AdoptionError(RuntimeError):
    """An adoption that cannot go on; the message says why."""


@dataclass(frozen=True)
class Observation:
    alive: bool
    # Changes whenever the agent does something visible; equal readings mean it is quiet.
    fingerprint: str
    screen: str | None


class Observer(Protocol):
    def look(self) -> Observation: ...


class OwnerTmux:
    """Read-only access to the owner's tmux server: list panes and capture them."""

    def __init__(self, socket: str | None, environ: Mapping[str, str] | None = None) -> None:
        self.socket = socket
        self.binary = shutil.which("tmux")
        source = os.environ if environ is None else environ
        self._env = client_environment(source)
        self._env.update({name: source[name] for name in OWNER_TMUX_VARIABLES if name in source})

    def _run(self, *args: str) -> str | None:
        if self.binary is None:
            return None
        socket = ("-L", self.socket) if self.socket else ()
        result = subprocess.run(
            [self.binary, *socket, *args], env=self._env, capture_output=True, text=True
        )
        return result.stdout if result.returncode == 0 else None

    def pane_of(self, pid: int) -> str | None:
        """The pane whose process is `pid` or one of its ancestors; None outside tmux."""
        listing = self._run("list-panes", "-a", "-F", "#{pane_id} #{pane_pid}")
        if not listing:
            return None
        panes = {int(pane_pid): pane for pane, pane_pid in _pairs(listing)}
        try:
            lineage = [pid, *(parent.pid for parent in psutil.Process(pid).parents())]
        except psutil.NoSuchProcess:
            return None
        return next((panes[ancestor] for ancestor in lineage if ancestor in panes), None)

    def capture(self, pane: str) -> str | None:
        text = self._run("capture-pane", "-p", "-J", "-t", pane)
        return None if text is None else "\n".join(line.rstrip() for line in text.splitlines())


def _pairs(listing: str) -> list[tuple[str, str]]:
    pairs = (line.split() for line in listing.splitlines())
    return [(fields[0], fields[1]) for fields in pairs if len(fields) == 2 and fields[1].isdigit()]


@dataclass
class PaneObserver:
    tmux: OwnerTmux
    pane: str
    pid: int
    started_at: float

    def look(self) -> Observation:
        screen = self.tmux.capture(self.pane)
        alive = is_alive(self.pid, self.started_at)
        return Observation(alive, _digest(screen or ""), screen)


@dataclass
class ProcessObserver:
    pid: int
    started_at: float

    def look(self) -> Observation:
        if not is_alive(self.pid, self.started_at):
            return Observation(False, "", None)
        try:
            process = psutil.Process(self.pid)
            times = process.cpu_times()
            children = sorted(child.pid for child in process.children(recursive=True))
        except psutil.NoSuchProcess:
            return Observation(False, "", None)
        # A running tool is a child process; a streaming reply burns CPU time.
        return Observation(True, f"{times.user + times.system:.2f} {children}", None)


def observer_for(tmux: OwnerTmux, pane: str | None, pid: int, started_at: float) -> Observer:
    if pane is None:
        return ProcessObserver(pid, started_at)
    return PaneObserver(tmux, pane, pid, started_at)


async def wait_for_turn_end(
    observer: Observer, clock: Clock, *, poll: float, quiet: float, timeout: float
) -> Observation:
    """Return once the agent stayed the same for `quiet` seconds, or exited."""
    seen = observer.look()
    changed_at = clock.now()
    deadline = changed_at + timedelta(seconds=timeout)
    while seen.alive:
        await clock.sleep(poll)
        now = clock.now()
        current = observer.look()
        if current.fingerprint != seen.fingerprint:
            changed_at = now
        seen = current
        if now - changed_at >= timedelta(seconds=quiet):
            return seen
        if now >= deadline:
            raise AdoptionError(f"the agent's turn did not end within {timeout:g} seconds")
    return seen


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
