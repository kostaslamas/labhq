"""One scan: running and saved sessions of every tool, grouped into projects. Free of cost.

The scan reads the process table, the tools' stores (ids, folders and times only), git, and
`gh` when it is logged in. It never reads conversation text and never calls a model.
"""

import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from labhq.adapters.tmux import AgentKinds, default_kinds
from labhq.adoption.discovery import Processes, RunningAgent, all_processes, discover
from labhq.clock import Clock, SystemClock
from labhq.inventory.git import Command, git_facts, run_command
from labhq.inventory.model import (
    GitFacts,
    Inventory,
    ProjectInventory,
    SavedEntry,
    SessionInfo,
    SessionState,
)
from labhq.inventory.probe import Probe, ProcessProbe
from labhq.inventory.projects import RootOf, group_by_project, propose_folder_managers
from labhq.inventory.propose import propose
from labhq.inventory.settings import InventorySettings, get_inventory_settings
from labhq.inventory.stores import AIDER, Bases, Context, aider_entries, read_all


class SessionScanner:
    def __init__(
        self,
        *,
        kinds: AgentKinds = default_kinds,
        settings: InventorySettings | None = None,
        clock: Clock | None = None,
        processes: Processes = all_processes,
        probe: Probe | None = None,
        home: Path | None = None,
        environ: Mapping[str, str] | None = None,
        root_of: RootOf | None = None,
        command: Command = run_command,
    ) -> None:
        self._kinds = kinds
        self._settings = settings or get_inventory_settings()
        self._clock = clock or SystemClock()
        self._processes = processes
        self._probe = probe or ProcessProbe(kinds, self._settings)
        self._environ = os.environ if environ is None else environ
        self._bases = Bases.for_user(home, self._environ)
        self._root_of = root_of
        self._command = command

    def scan(self) -> Inventory:
        now = self._clock.now()
        running = discover(self._kinds, self._processes)
        saved = self._saved(running)
        sessions = self._merge(running, saved)
        kwargs = {} if self._root_of is None else {"root_of": self._root_of}
        projects = group_by_project(sessions, **kwargs)
        for project in projects:
            project.git = self._git(project)
            project.proposals = [
                propose(session, project.git, now, self._settings) for session in project.sessions
            ]
        folders = propose_folder_managers(
            projects, minimum=self._settings.folder_manager_min_projects, home=self._bases.home
        )
        return Inventory(scanned_at=now, projects=projects, folders=folders)

    def _git(self, project: ProjectInventory) -> GitFacts:
        if not project.has_repo:
            return GitFacts()
        return git_facts(
            project.root,
            use_gh=self._settings.use_gh,
            timeout=self._settings.command_timeout_seconds,
            command=self._command,
        )

    def _saved(self, running: list[RunningAgent]) -> list[SavedEntry]:
        context = Context(self._bases, self._environ)
        entries = read_all(context)
        folders = {a.cwd for a in running} | {e.folder for e in entries}
        folders |= {Path(root) for root in self._settings.extra_roots}
        return entries + aider_entries(AIDER, tuple(sorted(f for f in folders if f.is_dir())))

    def _merge(self, running: list[RunningAgent], saved: list[SavedEntry]) -> list[SessionInfo]:
        """A running agent claims the newest unclaimed saved entry of its tool and folder."""
        now = self._clock.now()
        states = self._probe.states(running) if running else {}
        claimed: set[SavedEntry] = set()
        sessions: list[SessionInfo] = []
        for agent in running:
            entry = _newest_unclaimed(saved, claimed, agent)
            if entry is not None:
                claimed.add(entry)
            state = states.get(agent.pid, SessionState.IDLE)
            last = entry.updated_at if entry else None
            idle = 0.0 if state is SessionState.RUNNING else _seconds_since(last, agent, now)
            sessions.append(
                SessionInfo(
                    tool=agent.kind,
                    session_id=entry.session_id if entry else None,
                    folder=agent.cwd,
                    state=state,
                    last_activity=last,
                    idle_seconds=idle,
                    pid=agent.pid,
                    started_at=agent.started_at,
                    location=entry.location if entry else None,
                )
            )
        for entry in saved:
            if entry in claimed:
                continue
            resumable = self._resumable(entry.tool)
            sessions.append(
                SessionInfo(
                    tool=entry.tool,
                    session_id=entry.session_id,
                    folder=entry.folder,
                    state=SessionState.IDLE,
                    last_activity=entry.updated_at,
                    idle_seconds=max(0.0, (now - entry.updated_at).total_seconds()),
                    location=entry.location,
                    resumable=resumable,
                )
            )
        return sessions

    def _resumable(self, tool: str) -> bool:
        if tool not in self._kinds.names():
            return False
        return self._kinds.get(tool).continue_selected is not None


def _newest_unclaimed(
    saved: list[SavedEntry], claimed: set[SavedEntry], agent: RunningAgent
) -> SavedEntry | None:
    matches = [
        e
        for e in saved
        if e.tool == agent.kind and e not in claimed and e.folder.resolve() == agent.cwd.resolve()
    ]
    return max(matches, key=lambda e: e.updated_at, default=None)


def _seconds_since(last: datetime | None, agent: RunningAgent, now: datetime) -> float:
    moment = last or datetime.fromtimestamp(agent.started_at, tz=UTC)
    return max(0.0, (now - moment).total_seconds())
