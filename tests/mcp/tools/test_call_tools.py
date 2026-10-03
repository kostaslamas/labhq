"""ask_ceo and get_reply over HTTP, against the server's own Call Center."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from labhq.callcenter.calls import TicketState
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
