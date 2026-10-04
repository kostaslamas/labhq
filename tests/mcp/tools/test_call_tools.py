"""ask_ceo and get_reply over HTTP, against the server's own Call Center."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from labhq.callcenter.calls import CallCenter, Reply, TicketState
from labhq.mcp.server import build_app
from labhq.mcp.tools.calls import SPOKEN, call_center
from labhq.mcp.tools.registry import default_registry
from tests.mcp.tools.test_tool_calls import TOKEN, assert_spoken, call


@pytest.fixture
def client(
    database_url: str, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    monkeypatch.setenv("LABHQ_DATABASE_URL", database_url)
    # The fake agent answers "OK"; no test reaches a model.
    monkeypatch.setenv("LABHQ_CALLCENTER_AGENT_ADAPTER", "fake")
    with TestClient(build_app(default_registry, TOKEN), base_url="http://127.0.0.1") as c:
        center = call_center()
        yield c
        c.portal.call(center.close)
        c.portal.call(center.sessions.kw["bind"].dispose)


def _ticket(spoken: str) -> str:
    return spoken.split("Your ticket is ")[1].split(". ")[0]


def test_ask_ceo_returns_a_ticket_that_get_reply_redeems(client: TestClient) -> None:
    asked = call(client, "ask_ceo", question="What is the worker doing?")
    assert_spoken(asked)
    ticket = _ticket(asked)
    assert ticket.startswith("call-")

    client.portal.call(call_center().settle)
    reply = call(client, "get_reply", ticket=ticket)

    assert reply == "OK."
    assert_spoken(reply)


def test_get_reply_says_when_a_ticket_is_unknown(client: TestClient) -> None:
    reply = call(client, "get_reply", ticket="call-000000000000")
    assert reply == SPOKEN[TicketState.UNKNOWN]


def test_ask_ceo_refuses_an_empty_question(client: TestClient) -> None:
    assert call(client, "ask_ceo", question="  ") == "I did not hear the question."


def test_ask_ceo_with_wait_seconds_returns_the_answer_directly(client: TestClient) -> None:
    reply = call(client, "ask_ceo", question="What is the worker doing?", wait_seconds=30)

    assert reply == "OK."


def test_get_reply_waits_by_default_and_returns_a_ready_answer(client: TestClient) -> None:
    ticket = _ticket(call(client, "ask_ceo", question="What is the worker doing?"))
    client.portal.call(call_center().settle)

    assert call(client, "get_reply", ticket=ticket) == "OK."


def test_a_working_ticket_tells_the_caller_to_get_the_reply_and_not_ask_again(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def never(self: object, ticket: str, wait_seconds: float) -> Reply:
        return Reply(TicketState.WORKING)

    monkeypatch.setattr(CallCenter, "wait_for_reply", never)

    spoken = call(client, "get_reply", ticket="call-abc123abc123")

    assert_spoken(spoken)
    assert "call-abc123abc123" in spoken and "Do not ask the question again" in spoken
