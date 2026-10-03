"""`ask_ceo` returns a ticket at once; `get_reply` redeems it when the agent is done."""

import time
from datetime import timedelta

from sqlalchemy import select, update

from labhq.callcenter.calls import ROLE, TicketState
from labhq.callcenter.calls.service import OVER_BUDGET
from labhq.db.enums import CallRequestStatus, RunStatus
from labhq.db.models import Agent, CostEvent, Run, RunEvent
from labhq.speech import speakable
from tests.callcenter.calls.conftest import ANSWER, WINDOW, Line

TICKET_DEADLINE_SECONDS = 2


async def _use_adapter(line: Line, key: str) -> None:
    async with line.sessions() as db:
        await db.execute(update(Agent).where(Agent.role == ROLE).values(adapter=key))
        await db.commit()


async def test_ask_returns_a_ticket_in_under_two_seconds_while_the_agent_takes_thirty(
    line: Line,
) -> None:
    await line.center.ask("Warm up the line.")
    await line.center.settle()
    await _use_adapter(line, "slow")

    started = time.monotonic()
    ticket = await line.center.ask("What is the worker doing?")
    elapsed = time.monotonic() - started

    assert elapsed < TICKET_DEADLINE_SECONDS
    assert (await line.center.reply(ticket.ticket)).state is TicketState.WORKING
    assert (await line.request(ticket.ticket)).status is CallRequestStatus.PENDING


async def test_get_reply_redeems_the_ticket_with_the_agents_answer(line: Line) -> None:
    ticket = await line.center.ask("What is the worker doing?")
    await line.center.settle()

    reply = await line.center.reply(ticket.ticket)

    assert reply.state is TicketState.READY
    assert reply.text == ANSWER
    assert speakable(reply.text) == reply.text
    [request] = line.fake.requests
    assert "What is the worker doing?" in request.prompt
    assert ticket.ticket in request.prompt


async def test_an_unspeakable_answer_is_made_speakable_before_it_is_stored(line: Line) -> None:
    line.fake.text = "## Status\n- Worker: login form\n- Lead: reviewing"
    ticket = await line.center.ask("Status?")
    await line.center.settle()

    reply = await line.center.reply(ticket.ticket)

    assert reply.text is not None
    assert speakable(reply.text) == reply.text
    assert "login form" in reply.text


async def test_the_agent_has_its_own_row_and_every_call_records_its_cost(line: Line) -> None:
    ticket = await line.center.ask("What is the worker doing?")
    await line.center.settle()

    async with line.sessions() as db:
        agent = await db.scalar(select(Agent).where(Agent.role == ROLE))
        assert agent is not None and agent.budget_micros is not None
        [run] = (await db.scalars(select(Run))).all()
        assert (run.agent_id, run.task_id, run.status) == (agent.id, None, RunStatus.SUCCEEDED)
        [cost] = (await db.scalars(select(CostEvent))).all()
        assert (cost.agent_id, cost.run_id) == (agent.id, run.id)
        assert cost.cost_micros > 0
        link = await db.scalar(select(RunEvent).where(RunEvent.kind == "call_request"))
        assert link is not None
        assert link.payload == {"call_id": ticket.call_id, "request_id": ticket.ticket}


async def test_an_agent_over_budget_answers_that_it_is_without_running(line: Line) -> None:
    await line.center.ask("Warm up the line.")
    await line.center.settle()
    async with line.sessions() as db:
        await db.execute(update(Agent).where(Agent.role == ROLE).values(budget_micros=1))
        await db.commit()

    ticket = await line.center.ask("And now?")
    await line.center.settle()

    reply = await line.center.reply(ticket.ticket)
    assert (reply.state, reply.text) == (TicketState.FAILED, OVER_BUDGET)
    assert len(line.fake.requests) == 1


async def test_a_failed_turn_fails_the_ticket_with_a_spoken_reason(line: Line) -> None:
    line.fake.fail_with = RuntimeError("the CLI died")
    ticket = await line.center.ask("Status?")
    await line.center.settle()

    reply = await line.center.reply(ticket.ticket)
    assert reply.state is TicketState.FAILED
    assert reply.text is not None and speakable(reply.text) == reply.text


async def test_old_tickets_expire(line: Line) -> None:
    await line.center.ask("Warm up the line.")
    await line.center.settle()
    await _use_adapter(line, "slow")
    ticket = await line.center.ask("Status?")
    line.clock.advance(timedelta(seconds=WINDOW.ticket_expiry_seconds + 1))

    assert (await line.center.reply(ticket.ticket)).state is TicketState.EXPIRED
    assert (await line.request(ticket.ticket)).status is CallRequestStatus.EXPIRED


async def test_an_unknown_ticket_is_said_to_be_unknown(line: Line) -> None:
    assert (await line.center.reply("call-000000000000")).state is TicketState.UNKNOWN
