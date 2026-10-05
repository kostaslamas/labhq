"""The engine checks an adopted manager; it does not trust it to follow its rules (ADR 0005).

One pass per adopted agent:

- A turn that ended without a change to `.labhq/status.md` gets a request to update it,
  once until the agent updates it again.
- Rules that go as a message are sent again after a compaction notice or a new session.
- A change in the main checkout since the last pass notifies the owner.
- Plan percentages from the statusline are recorded, and the plan cap applies as to any
  labhq agent (ADR 0003): at the stop percentage labhq holds its own messages back.
"""

import asyncio
import hashlib
import re
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.adapters.tmux import AgentKind, AgentKinds, TmuxServer, TurnEnd, default_kinds
from labhq.adoption.checkout import changed_paths, fingerprint, is_git_repository
from labhq.adoption.rules import STATUS_REQUEST, rules_message, sends
from labhq.adoption.session import (
    AdoptedSession,
    file_digest,
    read_document,
    reported_session,
    send_message,
)
from labhq.adoption.settings import AdoptionSettings, get_adoption_settings
from labhq.adoption.state import AdoptionState, state_of, store_state
from labhq.budgets import Decision
from labhq.callcenter.status.ingest import ingest_status
from labhq.clock import Clock
from labhq.db.enums import AgentStatus
from labhq.db.models import Agent
from labhq.notify import enqueue as notify
from labhq.usage import UsageSettings, UsageUnit, check_agent
from labhq.usage.record import ReadingContext, record_readings
from labhq.usage.statusline import statusline_readings

CHECKOUT_CHANGED = "checkout_changed"
STATUSLINE_SOURCE = "statusline"
MAX_LISTED_PATHS = 10


@dataclass
class CheckReport:
    agent_id: int
    turn_ended: bool = False
    status_updated: bool = False
    status_requested: bool = False
    rules_sent: bool = False
    checkout_changed: bool = False
    # The plan cap held labhq's messages back this pass.
    held: bool = False
    session_id: str | None = None


class AdoptedChecks:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        clock: Clock,
        server: TmuxServer,
        kinds: AgentKinds = default_kinds,
        settings: AdoptionSettings | None = None,
        usage: UsageSettings | None = None,
    ) -> None:
        self._sessions = sessions
        self._clock = clock
        self._server = server
        self._kinds = kinds
        self._settings = settings or get_adoption_settings()
        self._usage = usage

    async def adopted(self) -> list[int]:
        query = select(Agent).where(Agent.status == AgentStatus.ACTIVE).order_by(Agent.id)
        async with self._sessions() as db:
            return [agent.id for agent in await db.scalars(query) if state_of(agent)]

    async def check_all(self) -> list[CheckReport]:
        return [await self.check(agent_id) for agent_id in await self.adopted()]

    async def check(self, agent_id: int) -> CheckReport:
        async with self._sessions() as db:
            agent = await db.get_one(Agent, agent_id)
            state = state_of(agent)
            if state is None:
                raise LookupError(f"agent {agent_id} was not adopted")
            report = await self._check(db, agent, state)
            store_state(agent, state)
            agent.updated_at = self._clock.now()
            await db.commit()
        return report

    async def _check(self, db: AsyncSession, agent: Agent, state: AdoptionState) -> CheckReport:
        kind = self._kinds.get(state.kind)
        session = AdoptedSession(state.tmux_session, Path(state.cwd), Path(state.state_dir))
        report = CheckReport(agent.id)
        held = await self._plan_holds(db, agent, kind, session, state)
        screen = await asyncio.to_thread(self._screen, session.name)
        compacted = self._compacted(kind, screen, state)
        report.turn_ended = self._turn_ended(kind, session, screen, state)
        reported = reported_session(kind, session)
        new_session = reported is not None and state.session_id not in (None, reported)
        state.session_id = reported or state.session_id
        report.session_id = state.session_id
        if sends(kind) and (compacted or new_session):
            state.rules_due = True
        messages: list[str] = [rules_message()] if state.rules_due else []
        if report.turn_ended:
            ingested = await ingest_status(
                db, self._clock, agent_id=agent.id, task_id=None, worktree=session.cwd
            )
            report.status_updated = ingested.changed
            if ingested.changed:
                state.status_requested = False
            elif not state.status_requested:
                messages.append(STATUS_REQUEST)
        if messages and held:
            report.held = True
        elif messages:
            for text in messages:
                await asyncio.to_thread(send_message, self._server, session.name, text)
            report.rules_sent = state.rules_due
            report.status_requested = STATUS_REQUEST in messages
            state.status_requested = state.status_requested or report.status_requested
            state.rules_due = False
        report.checkout_changed = await self._checkout(db, agent, state)
        return report

    def _screen(self, name: str) -> str:
        return self._server.capture(name) if self._server.has_session(name) else ""

    def _compacted(self, kind: AgentKind, screen: str, state: AdoptionState) -> bool:
        lines = screen.splitlines()
        # A cleared screen starts the count again.
        new = lines[state.screen_lines :] if len(lines) >= state.screen_lines else lines
        state.screen_lines = len(lines)
        pattern = kind.compaction_pattern
        return pattern is not None and any(re.search(pattern, line) for line in new)

    def _turn_ended(
        self, kind: AgentKind, session: AdoptedSession, screen: str, state: AdoptionState
    ) -> bool:
        if kind.turn_end is TurnEnd.SIGNAL:
            current = file_digest(session.signal_path)
            ended = current is not None and current != state.signal
            state.signal = current
            return ended
        # No turn signal: a turn ends when the screen changed and then stayed quiet.
        now = self._clock.now()
        current_screen = hashlib.sha256(screen.encode("utf-8")).hexdigest()
        if current_screen != state.screen:
            state.screen, state.changed_at, state.turn_open = current_screen, now, True
            return False
        quiet = timedelta(seconds=self._settings.quiescence_seconds)
        if state.turn_open and state.changed_at is not None and now - state.changed_at >= quiet:
            state.turn_open = False
            return True
        return False

    async def _plan_holds(
        self,
        db: AsyncSession,
        agent: Agent,
        kind: AgentKind,
        session: AdoptedSession,
        state: AdoptionState,
    ) -> bool:
        current = file_digest(session.statusline_path)
        document = read_document(session.statusline_path)
        if current != state.statusline and document is not None:
            # The statusline's cost is the session's running total; only plan percentages
            # are new information on every reading.
            readings = [
                reading
                for reading in statusline_readings(document)
                if reading.unit is UsageUnit.PERCENT
            ]
            context = ReadingContext(
                agent_id=agent.id,
                agent_kind=kind.name,
                run_id=None,
                project_id=agent.project_id,
                source=STATUSLINE_SOURCE,
                now=self._clock.now(),
            )
            record_readings(db, context, readings)
            await db.flush()
        state.statusline = current
        plan = await check_agent(db, agent, self._clock, self._usage, kind=kind.name)
        return plan.decision is Decision.STOP

    async def _checkout(self, db: AsyncSession, agent: Agent, state: AdoptionState) -> bool:
        repo = Path(state.repo)
        current = await asyncio.to_thread(fingerprint, repo)
        if current == state.baseline:
            return False
        paths = await asyncio.to_thread(changed_paths, repo)
        listed = ", ".join(paths[:MAX_LISTED_PATHS]) or (
            "a new commit" if is_git_repository(repo) else "files in the folder"
        )
        more = f" and {len(paths) - MAX_LISTED_PATHS} more" if len(paths) > MAX_LISTED_PATHS else ""
        await notify(
            db,
            kind=CHECKOUT_CHANGED,
            subject=f"agent:{agent.id}",
            title=f"The main checkout of agent {agent.id} changed",
            body=(
                f"{repo} changed after labhq adopted agent {agent.id}: {listed}{more}. "
                "A manager makes no code edits there; workers handle project files."
            ),
            idempotency_key=f"{CHECKOUT_CHANGED}:{agent.id}:{current}",
            now=self._clock.now(),
        )
        state.baseline = current
        return True
