"""`ask_ceo` and `get_reply`: a ticket at once, the Call Center agent's answer later.

`ask` stores the request and returns its ticket without waiting for any agent. A worker
task per call, in this process, answers the call's requests one at a time, because an agent
runs one turn at a time: each turn resumes the call's session, so follow-ups keep their
context, and two calls are two sessions working side by side.

The worker's exit and `ask`'s hand-off meet without a lock: both decide synchronously on
the event loop. A worker leaves only after a query found nothing and no `ask` woke it since;
an `ask` that finds no worker starts one.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.adapters import AdapterRegistry
from labhq.adapters import default_registry as builtin_adapters
from labhq.budgets import BudgetSettings, Decision, check
from labhq.callcenter.calls.agent import call_center_agent, prompt_for
from labhq.callcenter.calls.bounds import Interrupter, NoInterrupter
from labhq.callcenter.calls.settings import CallAgentSettings, get_call_agent_settings
from labhq.callcenter.calls.spoken import to_speech
from labhq.callcenter.calls.tickets import expire_if_old, next_pending, record_request
from labhq.callcenter.calls.tools import CallTools, internal_arguments
from labhq.callcenter.screens import ScreenReader, default_screen_reader
from labhq.callcenter.settings import CallCenterSettings, get_callcenter_settings
from labhq.clock import Clock
from labhq.db.enums import CallRequestStatus, RunStatus
from labhq.db.models import Call, CallRequest
from labhq.runs import RunService, RunStartError

log = logging.getLogger(__name__)

# A voice client gives up on a tool call after about a minute; stay under that.
MAX_WAIT_SECONDS = 50.0
POLL_SECONDS = 1.0

OVER_BUDGET = "The Call Center is over its budget for now, so I cannot look into that."
FAILED = "The Call Center could not finish that one. Please ask again."


class TicketState(StrEnum):
    READY = "ready"
    WORKING = "working"
    FAILED = "failed"
    EXPIRED = "expired"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Ticket:
    ticket: str
    call_id: int


@dataclass(frozen=True)
class Reply:
    state: TicketState
    text: str | None = None


@dataclass
class _Worker:
    task: "asyncio.Task[None] | None" = None
    # Set by `ask` while the worker runs: look for pending requests once more before leaving.
    wake: bool = False


@dataclass
class CallCenter:
    sessions: async_sessionmaker[AsyncSession]
    clock: Clock
    adapters: AdapterRegistry = builtin_adapters
    interrupter: Interrupter = field(default_factory=NoInterrupter)
    # Agent sessions are stored per working directory; every turn of a call uses this one.
    workdir: Path | None = None
    settings: CallCenterSettings = field(default_factory=get_callcenter_settings)
    agent_settings: CallAgentSettings = field(default_factory=get_call_agent_settings)
    budget_settings: BudgetSettings | None = None
    # Reads working agents' panes when a status is stale; None where tmux is missing.
    screens: ScreenReader | None = field(default_factory=default_screen_reader)
    _workers: dict[int, _Worker] = field(default_factory=dict, init=False)

    async def ask(self, text: str) -> Ticket:
        """Store the owner's words in the current call and start its agent; never waits on it."""
        async with self.sessions() as db:
            request = await record_request(db, self.clock, text, self.settings)
            call = await db.get_one(Call, request.call_id)
            if call.agent_id is None:
                call.agent_id = (await call_center_agent(db, self.clock, self.agent_settings)).id
            ticket = Ticket(request.request_id, call.id)
            await db.commit()
        self._ensure_worker(ticket.call_id)
        return ticket

    async def reply(self, ticket: str) -> Reply:
        async with self.sessions() as db:
            request = await db.scalar(select(CallRequest).where(CallRequest.request_id == ticket))
            if request is None:
                return Reply(TicketState.UNKNOWN)
            expired = await expire_if_old(db, request, self.clock.now(), self.settings)
            await db.commit()
            if expired:
                return Reply(TicketState.EXPIRED)
            if request.status is CallRequestStatus.ANSWERED:
                return Reply(TicketState.READY, request.reply)
            if request.status is CallRequestStatus.FAILED:
                return Reply(TicketState.FAILED, request.reply)
            call_id = request.call_id
        # A restart loses workers, not requests: a pending ticket gets its worker back.
        self._ensure_worker(call_id)
        return Reply(TicketState.WORKING)

    async def wait_for_reply(self, ticket: str, wait_seconds: float) -> Reply:
        """`reply`, polled until the answer is in or `wait_seconds` (at most 50) have passed."""
        deadline = self.clock.now() + timedelta(seconds=min(max(wait_seconds, 0), MAX_WAIT_SECONDS))
        while True:
            reply = await self.reply(ticket)
            remaining = (deadline - self.clock.now()).total_seconds()
            if reply.state is not TicketState.WORKING or remaining <= 0:
                return reply
            await self.clock.sleep(min(POLL_SECONDS, remaining))

    async def settle(self) -> None:
        """Wait until every call's worker has answered everything it was given."""
        while tasks := [w.task for w in self._workers.values() if w.task is not None]:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def close(self) -> None:
        tasks = [w.task for w in self._workers.values() if w.task is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def _ensure_worker(self, call_id: int) -> None:
        worker = self._workers.get(call_id)
        loop = asyncio.get_running_loop()
        if worker is not None and worker.task is not None and worker.task.get_loop() is loop:
            worker.wake = True
            return
        worker = _Worker()
        self._workers[call_id] = worker
        worker.task = loop.create_task(self._work(call_id, worker), name=f"call-{call_id}")

    async def _work(self, call_id: int, worker: _Worker) -> None:
        try:
            while True:
                worker.wake = False
                async with self.sessions() as db:
                    request = await next_pending(db, self.clock, call_id, self.settings)
                    request_pk = request.id if request is not None else None
                    await db.commit()
                if request_pk is not None:
                    await self._answer_safely(call_id, request_pk)
                elif not worker.wake:
                    return
        finally:
            if self._workers.get(call_id) is worker:
                del self._workers[call_id]

    async def _answer_safely(self, call_id: int, request_pk: int) -> None:
        try:
            await self._answer(call_id, request_pk)
        except Exception:
            log.exception("call %s: request %s failed", call_id, request_pk)
            await self._settle_request(call_id, request_pk, CallRequestStatus.FAILED, FAILED)

    async def _answer(self, call_id: int, request_pk: int) -> None:
        async with self.sessions() as db:
            request = await db.get_one(CallRequest, request_pk)
            call = await db.get_one(Call, call_id)
            agent_id = (
                call.agent_id or (await call_center_agent(db, self.clock, self.agent_settings)).id
            )
            budget = await check(db, agent_id, self.clock, self.budget_settings)
            prompt = prompt_for(request, first_turn=call.session_id is None)
            resume, request_id = call.session_id, request.request_id
            await db.commit()
        if budget.decision is Decision.STOP:
            await self._settle_request(call_id, request_pk, CallRequestStatus.FAILED, OVER_BUDGET)
            return

        if self.workdir is not None:
            self.workdir.mkdir(parents=True, exist_ok=True)
        tools = CallTools(
            self.sessions, self.clock, self.interrupter, call_id, self.screens
        ).specs()
        runs = RunService(self.sessions, clock=self.clock, registry=self.adapters)
        try:
            active = await runs.start(
                agent_id=agent_id,
                task_id=None,
                prompt=prompt,
                cwd=self.workdir,
                resume_session_id=resume,
                tools=tools,
                # An agent in tmux gets the same tools from its CLI's own stdio child.
                tools_server=internal_arguments(call_id),
            )
        except RunStartError:
            log.exception("call %s: the Call Center agent did not start", call_id)
            await self._settle_request(call_id, request_pk, CallRequestStatus.FAILED, FAILED)
            return
        # Links the run, and so its cost, to the call and the request it served.
        await active.note("call_request", {"call_id": call_id, "request_id": request_id})
        run = await active.wait()
        if run.status is not RunStatus.SUCCEEDED or active.result is None:
            await self._settle_request(call_id, request_pk, CallRequestStatus.FAILED, FAILED)
            return
        await self._settle_request(
            call_id,
            request_pk,
            CallRequestStatus.ANSWERED,
            to_speech(active.result.text),
            session_id=run.session_id_after,
        )

    async def _settle_request(
        self,
        call_id: int,
        request_pk: int,
        status: CallRequestStatus,
        reply: str,
        *,
        session_id: str | None = None,
    ) -> None:
        async with self.sessions() as db:
            request = await db.get_one(CallRequest, request_pk)
            request.status = status
            request.reply = reply
            request.answered_at = self.clock.now()
            if session_id is not None:
                call = await db.get_one(Call, call_id)
                call.session_id = session_id
            await db.commit()
