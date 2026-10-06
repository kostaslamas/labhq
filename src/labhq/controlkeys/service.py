"""Send a named control key to an agent's live tmux pane, and record that it was sent.

The owner may send any key the agent's kind lists. An agent may send `escape` only, and only
to an agent that reports to it directly: `shift_tab` changes the permission mode, so it and
`ctrl_c` stay with the owner. Both limits are data below. Every key sent is a `control_key`
event on the agent's running run, so it shows in the agent's activity with the sender.

The Call Center never imports this package (ADR 0004).
"""

import asyncio
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.adapters.tmux import (
    TmuxError,
    TmuxServer,
    UnknownAgentKindError,
    default_kinds,
    get_tmux_settings,
)
from labhq.adapters.tmux.agents import AgentKinds
from labhq.adapters.tmux.controlkeys import CONTROL_KEYS, ControlKeyRefusedError, tmux_key
from labhq.adapters.tmux.server import PaneState, TmuxMissingError
from labhq.callcenter.screens import pane_of_run, running_tmux_run
from labhq.clock import Clock
from labhq.db.enums import AgentStatus
from labhq.db.models import Agent, RunEvent
from labhq.hierarchy import CEO, HEAD, LEAD, MANAGER
from labhq.settings import get_settings

CONTROL_KEY_EVENT = "control_key"
OWNER = "owner"
# What an agent may send, and the roles that may send it.
AGENT_KEYS = frozenset({"escape"})
AGENT_SENDER_ROLES = frozenset({CEO, MANAGER, HEAD, LEAD})


class KeyPanes(Protocol):
    def send_keys(self, name: str, *keys: str, literal: bool = False) -> None: ...

    def capture(self, name: str) -> str: ...

    def pane_state(self, name: str) -> PaneState: ...


class ControlKeyError(Exception):
    """A refusal with a stable `code` for the API and a message that says what to change."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Sender:
    label: str
    agent_id: int | None = None


OWNER_SENDER = Sender(OWNER)


def agent_sender(agent_id: int) -> Sender:
    return Sender(f"agent:{agent_id}", agent_id)


@dataclass(frozen=True)
class KeySupport:
    keys: list[str]
    live: bool


class ControlKeyService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        clock: Clock,
        panes: KeyPanes | None,
        kinds: AgentKinds = default_kinds,
    ) -> None:
        self._sessions = sessions
        self._clock = clock
        self._panes = panes
        self._kinds = kinds

    async def support(self, agent_id: int) -> KeySupport:
        """The keys the agent's live pane accepts; empty without a live tmux pane."""
        async with self._sessions() as db:
            agent = await _active_agent(db, agent_id)
            run = await running_tmux_run(db, agent_id=agent.id)
            if run is None or self._panes is None:
                return KeySupport(keys=[], live=False)
            _, kind_name = await pane_of_run(db, run)
        try:
            return KeySupport(keys=list(self._kinds.get(kind_name).control_keys), live=True)
        except UnknownAgentKindError:
            return KeySupport(keys=[], live=False)

    async def send(self, sender: Sender, agent_id: int, key: str) -> str:
        """Send `key`; returns the pane's screen taken right after, empty if unreadable."""
        async with self._sessions() as db:
            agent = await _active_agent(db, agent_id)
            await _check_sender(db, sender, agent, key)
            panes = self._panes
            run = await running_tmux_run(db, agent_id=agent.id)
            if run is None or panes is None:
                raise ControlKeyError("no_pane", _NO_PANE.format(agent.id))
            name, kind_name = await pane_of_run(db, run)
            try:
                tmux_name = tmux_key(self._kinds.get(kind_name), key)
            except (ControlKeyRefusedError, UnknownAgentKindError) as error:
                raise ControlKeyError("key_refused", str(error)) from None
            try:
                if (await asyncio.to_thread(panes.pane_state, name)).dead:
                    raise ControlKeyError("no_pane", _NO_PANE.format(agent.id))
                await asyncio.to_thread(panes.send_keys, name, tmux_name)
            except TmuxError:
                raise ControlKeyError("no_pane", _NO_PANE.format(agent.id)) from None
            seq = await db.scalar(select(func.max(RunEvent.seq)).where(RunEvent.run_id == run.id))
            db.add(
                RunEvent(
                    run_id=run.id,
                    seq=(seq or 0) + 1,
                    kind=CONTROL_KEY_EVENT,
                    payload={
                        "sender": sender.label,
                        "target": agent.id,
                        "key": key,
                        "tmux_key": tmux_name,
                    },
                    created_at=self._clock.now(),
                )
            )
            await db.commit()
        return await self._screen(panes, name)

    async def screen(self, agent_id: int) -> str | None:
        async with self._sessions() as db:
            agent = await _active_agent(db, agent_id)
            run = await running_tmux_run(db, agent_id=agent.id)
            if run is None or self._panes is None:
                return None
            name, _ = await pane_of_run(db, run)
        return await self._screen(self._panes, name) or None

    @staticmethod
    async def _screen(panes: KeyPanes, name: str) -> str:
        try:
            return await asyncio.to_thread(panes.capture, name)
        except TmuxError:
            return ""


_NO_PANE = "Agent {} has no live tmux pane, so there is nothing to send the key to."


async def _active_agent(db: AsyncSession, agent_id: int) -> Agent:
    agent = await db.get(Agent, agent_id)
    if agent is None or agent.status == AgentStatus.RETIRED:
        raise ControlKeyError("agent_not_found", f"There is no active agent {agent_id}.")
    return agent


async def _check_sender(db: AsyncSession, sender: Sender, target: Agent, key: str) -> None:
    if sender.agent_id is None:
        if key not in CONTROL_KEYS:
            raise ControlKeyError("key_refused", f"Unknown control key {key!r}.")
        return
    caller = await db.get(Agent, sender.agent_id)
    if caller is None or caller.role not in AGENT_SENDER_ROLES:
        raise ControlKeyError("not_permitted", "Your role may not send control keys.")
    if key not in AGENT_KEYS:
        raise ControlKeyError(
            "not_permitted", f"Only the owner may send {key!r}; you may send: escape."
        )
    if target.reports_to != caller.id:
        raise ControlKeyError("not_permitted", "You may send keys only to your direct reports.")


def default_control_keys(
    sessions: async_sessionmaker[AsyncSession], clock: Clock
) -> ControlKeyService:
    """The service on labhq's private tmux server; without tmux there is never a live pane."""
    try:
        panes: KeyPanes | None = TmuxServer(
            socket=get_tmux_settings().socket, state_dir=get_settings().data_dir / "tmux"
        )
    except TmuxMissingError:
        panes = None
    return ControlKeyService(sessions, clock, panes)
