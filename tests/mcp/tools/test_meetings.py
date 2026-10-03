"""`meeting_minutes` over MCP: listed read-only, answers from the database alone."""

import time
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.testclient import TestClient

import labhq.mcp.tools  # noqa: F401  (registers every tool)
from labhq.clock import FakeClock
from labhq.db.models import Run
from labhq.mcp.server import build_app
from labhq.mcp.tools import meetings
from labhq.mcp.tools.registry import default_registry
from labhq.speech import speakable
from tests.callcenter.answers.minutes_seed import add_meeting, add_team

TOKEN = "meetings-tool-token"
HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
    "Authorization": f"Bearer {TOKEN}",
}
BUDGET_SECONDS = 2.0


@pytest.fixture
def client(
    database_url: str, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    monkeypatch.setenv("LABHQ_DATABASE_URL", database_url)
    monkeypatch.setattr(meetings, "CLOCK", clock)
    with TestClient(build_app(default_registry, TOKEN), base_url="http://127.0.0.1") as c:
        yield c


def rpc(client: TestClient, method: str, params: dict[str, Any]) -> dict[str, Any]:
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    result: dict[str, Any] = client.post("/mcp", json=payload, headers=HEADERS).json()["result"]
    return result


def minutes(client: TestClient, **arguments: str) -> str:
    result = rpc(client, "tools/call", {"name": "meeting_minutes", "arguments": arguments})
    assert not result.get("isError"), result
    return str(result["content"][0]["text"])


def test_tools_list_shows_meeting_minutes_as_read_only(client: TestClient) -> None:
    tools = {tool["name"]: tool for tool in rpc(client, "tools/list", {})["tools"]}

    tool = tools["meeting_minutes"]
    assert tool["annotations"]["readOnlyHint"] is True
    assert "meeting" in tool["inputSchema"]["properties"]
    assert "meeting" not in tool["inputSchema"].get("required", [])


def test_it_answers_on_an_empty_database(client: TestClient) -> None:
    assert minutes(client) == "No meeting has been held yet."


async def test_it_reads_a_standup_within_two_seconds_without_an_agent(
    client: TestClient, session: AsyncSession, clock: FakeClock
) -> None:
    team = await add_team(session, clock.now(), "demo")
    await add_meeting(session, team, clock.now() - timedelta(hours=1))
    runs = await session.scalar(select(func.count()).select_from(Run))

    started = time.perf_counter()
    text = minutes(client, meeting="this morning's standup")
    elapsed = time.perf_counter() - started

    assert elapsed < BUDGET_SECONDS
    assert speakable(text) == text
    assert text.startswith("The standup for demo ended 1 hour ago.")
    assert "Decision 1: Ship the parser first." in text
    session.expire_all()
    assert await session.scalar(select(func.count()).select_from(Run)) == runs
