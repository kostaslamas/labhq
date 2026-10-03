"""`wait_for_reply` long-polls a ticket: it returns once the answer is in, never past the cap."""

from collections.abc import Callable
from datetime import timedelta

from sqlalchemy import update

from labhq.callcenter.calls import ROLE, TicketState
from labhq.callcenter.calls.service import MAX_WAIT_SECONDS
from labhq.clock import FakeClock
from labhq.db.models import Agent
from tests.callcenter.calls.conftest import ANSWER, Line


class HookClock(FakeClock):
    """A fake clock that tells the test about every sleep, so it can act mid-wait."""

    def __init__(self, start: FakeClock, on_sleep: Callable[[int], None]) -> None:
        super().__init__(start.now())
        self._on_sleep = on_sleep
        self.sleeps = 0

    async def sleep(self, seconds: float) -> None:
        self.sleeps += 1
        self._on_sleep(self.sleeps)
        await super().sleep(seconds)


async def _gated(line: Line) -> None:
    async with line.sessions() as db:
        await db.execute(update(Agent).where(Agent.role == ROLE).values(adapter="gated"))
        await db.commit()


async def test_a_ready_answer_returns_at_once_without_sleeping(line: Line) -> None:
    ticket = await line.center.ask("What is the worker doing?")
    await line.center.settle()
    started = line.clock.now()

    reply = await line.center.wait_for_reply(ticket.ticket, 50)

    assert (reply.state, reply.text) == (TicketState.READY, ANSWER)
    assert line.clock.now() == started


async def test_the_answer_that_arrives_mid_wait_ends_the_wait(line: Line) -> None:
    await line.center.ask("Warm up the line.")
    await line.center.settle()
    await _gated(line)
    clock = HookClock(line.clock, lambda n: line.gate.set() if n == 3 else None)
    line.center.clock = clock
    ticket = await line.center.ask("What is the worker doing?")
    started = clock.now()

    reply = await line.center.wait_for_reply(ticket.ticket, 50)

    assert (reply.state, reply.text) == (TicketState.READY, ANSWER)
    assert clock.now() - started < timedelta(seconds=MAX_WAIT_SECONDS)


async def test_the_wait_never_outlasts_the_cap_and_ends_working(line: Line) -> None:
    await line.center.ask("Warm up the line.")
    await line.center.settle()
    await _gated(line)
    ticket = await line.center.ask("What is the worker doing?")
    started = line.clock.now()

    reply = await line.center.wait_for_reply(ticket.ticket, 600)

    assert reply.state is TicketState.WORKING
    assert line.clock.now() - started == timedelta(seconds=MAX_WAIT_SECONDS)
    line.gate.set()


async def test_no_wait_asked_is_a_single_look(line: Line) -> None:
    await line.center.ask("Warm up the line.")
    await line.center.settle()
    await _gated(line)
    ticket = await line.center.ask("What is the worker doing?")
    started = line.clock.now()

    reply = await line.center.wait_for_reply(ticket.ticket, 0)

    assert reply.state is TicketState.WORKING
    assert line.clock.now() == started
    line.gate.set()


async def test_a_blocked_run_ends_the_wait_with_a_spoken_failure_not_working(line: Line) -> None:
    line.fake.subtype, line.fake.is_error = "error_blocked", True
    line.fake.terminal_reason, line.fake.text = "blocked_dialog", None
    ticket = await line.center.ask("What is the worker doing?")

    reply = await line.center.wait_for_reply(ticket.ticket, 50)

    assert reply.state is TicketState.FAILED
    assert reply.text and "could not finish" in reply.text
