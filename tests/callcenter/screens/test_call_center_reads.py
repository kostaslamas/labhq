"""The Call Center answers from a fresh status, and from the manager's screen when it is stale.

The manager runs a fake agent in a real private tmux server; the Call Center is a fake
agent that asks its `agent_status` tool about the manager and answers with what it read.
Neither path delivers anything to the manager or sends a key to its pane.
"""

from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from labhq.adapters import AdapterEvent, FakeAdapter, FakeScript, default_registry
from labhq.callcenter.calls import CallCenter, TicketState
from labhq.callcenter.calls.settings import CallAgentSettings
from labhq.callcenter.settings import CallCenterSettings
from labhq.db.models import Delivery, WakeupRequest
from tests.callcenter.screens.conftest import SUMMARY, Office

pytestmark = pytest.mark.posix_only("the tmux adapter does not run on native Windows (ADR 0003)")

WINDOW = CallCenterSettings(call_window_seconds=300, ticket_expiry_seconds=3600)


class ReadingAgent(FakeAdapter):
    """A fake Call Center agent: it reads the manager's status and replies with it."""

    def __init__(self, script: FakeScript, manager_id: int, readings: list[str]) -> None:
        super().__init__(script)
        self._manager_id = manager_id
        self._readings = readings

    async def events(self) -> AsyncIterator[AdapterEvent]:
        assert self._request is not None
        tools = {tool.name: tool for tool in self._request.tools}
        reading = await tools["agent_status"].handler({"agent_id": self._manager_id})
        self._readings.append(reading)
        self.script.text = reading
        async for event in super().events():
            yield event


@pytest.fixture
async def center(office: Office) -> AsyncIterator[tuple[CallCenter, list[str]]]:
    readings: list[str] = []
    script = FakeScript()
    registry = default_registry.copy()
    registry.register("reading", lambda: ReadingAgent(script, office.manager_id, readings))
    call_center = CallCenter(
        office.sessions,
        office.clock,
        adapters=registry,
        settings=WINDOW,
        agent_settings=CallAgentSettings(agent_adapter="reading"),
        screens=office.reader,
    )
    try:
        yield call_center, readings
    finally:
        await call_center.close()


async def _nothing_reached_the_manager(office: Office) -> None:
    async with office.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Delivery)) == 0
        assert await db.scalar(select(func.count()).select_from(WakeupRequest)) == 0
    assert office.server.keys_sent() == []
    assert "received:" not in office.screen()


async def test_with_a_fresh_status_it_answers_from_the_status(
    office: Office, center: tuple[CallCenter, list[str]]
) -> None:
    call_center, readings = center
    ticket = await call_center.ask("How is the demo project going?")
    await call_center.settle()

    reply = await call_center.reply(ticket.ticket)
    [reading] = readings
    assert reply.state is TicketState.READY
    assert "fresh" in reading and SUMMARY in reading
    assert "screen" not in reading
    assert reply.text is not None and "Wiring the login form" in reply.text
    await _nothing_reached_the_manager(office)


async def test_with_a_stale_status_it_answers_from_the_managers_screen(
    office: Office, center: tuple[CallCenter, list[str]]
) -> None:
    call_center, readings = center
    # An earlier look at the team saw the screen as it was when the status was written.
    async with office.sessions() as db:
        await office.reader.capture(db, office.clock, agent_id=office.manager_id)
    office.clock.advance(timedelta(minutes=2))
    await office.progress("manager: tests pass, opening the pull request")

    ticket = await call_center.ask("How is the demo project going?")
    await call_center.settle()

    reply = await call_center.reply(ticket.ticket)
    [reading] = readings
    assert reply.state is TicketState.READY
    assert "stale" in reading
    assert "Its screen now, read without sending it anything" in reading
    assert "manager: tests pass, opening the pull request" in reading
    assert reply.text is not None and "opening the pull request" in reply.text
    await _nothing_reached_the_manager(office)
