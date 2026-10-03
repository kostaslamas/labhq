"""A call is a window of time: inside it the agent resumes its session, after it a new call."""

from datetime import timedelta

from sqlalchemy import func, select, update

from labhq.callcenter.calls import ROLE, TicketState
from labhq.db.enums import CallStatus, RunStatus
from labhq.db.models import Agent, Call, Run
from tests.callcenter.calls.conftest import Line


async def _calls(line: Line) -> list[Call]:
    async with line.sessions() as db:
        return list((await db.scalars(select(Call).order_by(Call.id))).all())


async def test_a_second_ask_inside_the_window_resumes_the_same_session(line: Line) -> None:
    first = await line.center.ask("What is the worker doing?")
    await line.center.settle()
    line.clock.advance(timedelta(seconds=120))

    second = await line.center.ask("And what is next for it?")
    await line.center.settle()

    assert second.call_id == first.call_id
    opening, follow_up = line.fake.requests
    assert opening.resume_session_id is None
    assert follow_up.resume_session_id == line.fake.session_id
    # The rules are given once per call; a resumed session already has them.
    assert "You are the Call Center" in opening.prompt
    assert "You are the Call Center" not in follow_up.prompt
    [call] = await _calls(line)
    assert call.session_id == line.fake.session_id
    assert (await line.center.reply(second.ticket)).state is TicketState.READY


async def test_after_the_window_a_new_call_starts_a_new_session(line: Line) -> None:
    first = await line.center.ask("What is the worker doing?")
    await line.center.settle()
    line.after_window()

    second = await line.center.ask("Anything new?")
    await line.center.settle()

    assert second.call_id != first.call_id
    assert [r.resume_session_id for r in line.fake.requests] == [None, None]
    old, new = await _calls(line)
    assert (old.status, new.status) == (CallStatus.CLOSED, CallStatus.OPEN)
    assert old.closed_at == line.clock.now()


async def test_asks_that_arrive_while_the_agent_works_are_answered_in_turn(line: Line) -> None:
    tickets = [await line.center.ask(f"Question {n}?") for n in range(3)]
    await line.center.settle()

    assert [(await line.center.reply(t.ticket)).state for t in tickets] == [TicketState.READY] * 3
    prompts = [request.prompt for request in line.fake.requests]
    assert len(prompts) == 3
    assert all(t.ticket in prompt for t, prompt in zip(tickets, prompts, strict=True))
    assert [r.resume_session_id for r in line.fake.requests[1:]] == [line.fake.session_id] * 2


async def test_two_calls_at_once_are_two_agents_working_side_by_side(line: Line) -> None:
    await line.center.ask("Warm up the line.")
    await line.center.settle()
    async with line.sessions() as db:
        await db.execute(update(Agent).where(Agent.role == ROLE).values(adapter="gated"))
        await db.commit()
    line.after_window()
    first = await line.center.ask("What is the worker doing?")
    await _until_running(line, 1)
    # The first call's turn outlasts its window, so the next question opens a second call.
    line.after_window()
    second = await line.center.ask("Who is blocked?")
    await _until_running(line, 2)

    assert second.call_id != first.call_id
    line.gate.set()
    await line.center.settle()
    assert (await line.center.reply(first.ticket)).state is TicketState.READY
    assert (await line.center.reply(second.ticket)).state is TicketState.READY


async def _until_running(line: Line, count: int) -> None:
    # Yield to the workers until they started their runs; no wall-clock wait.
    for _ in range(1000):
        async with line.sessions() as db:
            running = await db.scalar(
                select(func.count()).select_from(Run).where(Run.status == RunStatus.RUNNING)
            )
        if running == count:
            return
        await line.clock.sleep(0)
    raise AssertionError(f"expected {count} running Call Center turns")
