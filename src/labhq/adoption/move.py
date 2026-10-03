"""The move (ADR 0005): wait for the turn to end, end the process, continue it on labhq's
private tmux server, then record the agent as the project's manager.

The original process is gone before the continued one starts, so two processes never
drive one conversation. Uncommitted changes in the checkout are left exactly as they are
and listed in the status.
"""

import asyncio
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

import psutil
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.adapters.tmux import AgentKinds, TmuxServer, default_kinds, get_tmux_settings
from labhq.adapters.tmux.agents import default_python
from labhq.adapters.tmux.turns import Watch, quiescent
from labhq.adoption.checkout import changed_paths, fingerprint, toplevel
from labhq.adoption.discovery import is_alive
from labhq.adoption.observe import AdoptionError, OwnerTmux, observer_for, wait_for_turn_end
from labhq.adoption.record import Adopted, record_adoption
from labhq.adoption.request import AdoptPayload, refuse_second_manager
from labhq.adoption.rules import rules_message, sends, write_rules
from labhq.adoption.session import (
    AdoptedSession,
    reported_session,
    send_message,
    session_name,
    start_session,
)
from labhq.adoption.settings import AdoptionSettings, get_adoption_settings
from labhq.clock import Clock, SystemClock
from labhq.db import create_engine, session_factory
from labhq.hierarchy import HierarchySettings
from labhq.settings import Settings, get_settings
from labhq.worktrees.exclude import exclude_state_dir


def default_server() -> TmuxServer:
    return TmuxServer(socket=get_tmux_settings().socket, state_dir=get_settings().data_dir / "tmux")


def configured_database_url() -> str:
    # Read on every execution, like the hierarchy executors: one process may serve several.
    return Settings().resolved_database_url


def end_process(pid: int, started_at: float, timeout: float) -> None:
    """End the original agent: SIGTERM, then SIGKILL; return only once it is gone."""
    if not is_alive(pid, started_at):
        return
    process = psutil.Process(pid)
    try:
        process.terminate()
        process.wait(timeout)
    except psutil.TimeoutExpired:
        process.kill()
        process.wait(timeout)
    except psutil.NoSuchProcess:
        return
    if is_alive(pid, started_at):
        raise AdoptionError(f"process {pid} did not end; nothing was continued")


@dataclass(frozen=True)
class AdoptionEngine:
    """Everything the `adopt_agent` executor needs besides its payload."""

    server: Callable[[], TmuxServer] = default_server
    kinds: AgentKinds = default_kinds
    clock: Clock = field(default_factory=SystemClock)
    database_url: Callable[[], str] = configured_database_url
    settings: Callable[[], AdoptionSettings] = get_adoption_settings
    hierarchy: Callable[[], HierarchySettings] = HierarchySettings
    environ: Mapping[str, str] | None = None
    python: str | None = None

    def run(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Called from the approval service's worker thread, with only the payload."""
        return asyncio.run(self.adopt(AdoptPayload.model_validate(payload)))

    async def adopt(self, request: AdoptPayload) -> dict[str, Any]:
        engine = create_engine(self.database_url())
        sessions = session_factory(engine)
        try:
            async with sessions() as db:
                await refuse_second_manager(db, request.project)
            adopted = await self._move(request)
            async with sessions() as db:
                record = await self._record(db, request, adopted)
                await db.commit()
        finally:
            await engine.dispose()
        return record

    async def _move(self, request: AdoptPayload) -> Adopted:
        kind = self.kinds.get(request.kind)
        settings = self.settings()
        cwd = Path(request.cwd)
        repo = toplevel(cwd)
        tmux = OwnerTmux(settings.owner_tmux_socket, self.environ)
        observer = observer_for(tmux, request.pane, request.pid, request.started_at)
        last = await wait_for_turn_end(
            observer,
            self.clock,
            poll=settings.poll_seconds,
            quiet=settings.quiescence_seconds,
            timeout=settings.turn_timeout_seconds,
        )
        await asyncio.to_thread(
            end_process, request.pid, request.started_at, settings.end_timeout_seconds
        )
        # Exclude first, so the snapshot of uncommitted work never lists labhq's own files.
        exclude_state_dir(cwd)
        uncommitted = changed_paths(repo)
        write_rules(cwd)
        server = self.server()
        name = session_name(request.pid)
        session = AdoptedSession(name, cwd, server.state_dir / "adopted" / name)
        await asyncio.to_thread(
            start_session,
            server,
            kind,
            session,
            environ=self.environ if self.environ is not None else os.environ,
            python=self.python or default_python(),
            sandbox=settings.sandbox,
        )
        if sends(kind):
            await self._wait_ready(server, name, settings)
            await asyncio.to_thread(send_message, server, name, rules_message())
        session_id = await self._await_session(kind_name=kind.name, session=session)
        return Adopted(
            kind=kind,
            session=session,
            repo=repo,
            session_id=session_id,
            uncommitted=uncommitted,
            baseline=fingerprint(repo),
            last_screen=last.screen,
        )

    async def _wait_ready(self, server: TmuxServer, name: str, settings: AdoptionSettings) -> None:
        watch = Watch(screen="", last_change_at=self.clock.now())
        quiet = timedelta(seconds=settings.ready_seconds)
        deadline = self.clock.now() + timedelta(seconds=settings.ready_timeout_seconds)
        while self.clock.now() < deadline:
            await self.clock.sleep(settings.poll_seconds)
            screen = await asyncio.to_thread(server.capture, name)
            now = self.clock.now()
            if screen != watch.screen:
                watch.screen, watch.last_change_at, watch.changed = screen, now, True
            elif quiescent(watch, now, quiet):
                return
        raise AdoptionError(f"the continued agent in {name} never became ready for its rules")

    async def _await_session(self, *, kind_name: str, session: AdoptedSession) -> str | None:
        kind = self.kinds.get(kind_name)
        settings = self.settings()
        deadline = self.clock.now() + timedelta(seconds=settings.session_wait_seconds)
        while True:
            found = reported_session(kind, session)
            if found is not None or self.clock.now() >= deadline:
                return found
            await self.clock.sleep(settings.poll_seconds)

    async def _record(
        self, db: AsyncSession, request: AdoptPayload, adopted: Adopted
    ) -> dict[str, Any]:
        return await record_adoption(
            db,
            self.clock,
            request=request,
            adopted=adopted,
            ceo_adapter=self.hierarchy().org_adapter,
        )
