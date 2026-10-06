import json
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.testclient import TestClient

import labhq.mcp.tools  # noqa: F401  (registers every tool)
from labhq.callcenter.answers.refs import approval_ref, question_ref
from labhq.ceochat import message_text
from labhq.clock import FakeClock
from labhq.db.enums import ApprovalStatus, QuestionStatus, RiskClass, WakeupSource
from labhq.db.models import AgentQuestion, Approval, Call, CallRequest, Task, WakeupRequest
from labhq.mcp.server import build_app
from labhq.mcp.tools.registry import default_registry
from labhq.speech import speakable
from tests.callcenter.answers.seed import seed_busy
from tests.callcenter.factories import add_ceo
from tests.db.factories import project_agent_task

TOKEN = "tool-test-token"
HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
    "Authorization": f"Bearer {TOKEN}",
}


@pytest.fixture
def client(database_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("LABHQ_DATABASE_URL", database_url)
    with TestClient(build_app(default_registry, TOKEN), base_url="http://127.0.0.1") as c:
        yield c


def call(client: TestClient, name: str, **arguments: Any) -> str:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }
    result = client.post("/mcp", json=payload, headers=HEADERS).json()["result"]
    assert not result.get("isError"), result
    return str(result["content"][0]["text"])


def assert_spoken(text: str) -> None:
    """No markdown table, no JSON, and `speakable` accepts it."""
    assert text
    assert speakable(text) == text
    assert "|" not in text
    with pytest.raises(json.JSONDecodeError):
        json.loads(text)


async def count(session: AsyncSession, model: type) -> int:
    session.expire_all()
    return await session.scalar(select(func.count()).select_from(model)) or 0


def test_tools_list_reports_every_registered_tool_with_annotations(client: TestClient) -> None:
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    tools = client.post("/mcp", json=payload, headers=HEADERS).json()["result"]["tools"]
    assert {t["name"] for t in tools} == {spec.name for spec in default_registry}
    assert all(t["annotations"] for t in tools)


def test_every_read_tool_answers_on_an_empty_database(client: TestClient) -> None:
    for name in ("brief", "inbox", "health", "reports"):
        assert_spoken(call(client, name))


async def test_every_tool_answers_in_speakable_text_on_a_seeded_database(
    session: AsyncSession, clock: FakeClock, client: TestClient
) -> None:
    ids = await seed_busy(session, clock)
    answers = [
        call(client, "brief"),
        call(client, "inbox"),
        call(client, "health"),
        call(client, "decide", reference=approval_ref(ids["approval"]), verdict="approve"),
        call(client, "order", text="Fix the login bug"),
        call(client, "reports"),
        call(client, "answer", reference=question_ref(ids["question"]), words="Release from main."),
    ]

    for text in answers:
        assert_spoken(text)


async def test_a_heavy_decide_leaves_a_pending_approval_and_executes_nothing(
    session: AsyncSession, clock: FakeClock, client: TestClient
) -> None:
    row = Approval(type="push", risk_class=RiskClass.HEAVY, payload={}, created_at=clock.now())
    session.add(row)
    await session.commit()
    approval_id = row.id
    tasks_before = await count(session, Task)

    text = call(client, "decide", reference=approval_ref(approval_id), verdict="approve")

    stored = await session.get_one(Approval, approval_id)
    assert stored.status is ApprovalStatus.PENDING
    assert stored.decided_by is None
    assert await count(session, Task) == tasks_before
    assert "passkey" in text
    assert_spoken(text)


async def test_an_mcp_order_reaches_the_ceo_verbatim_and_creates_no_task(
    session: AsyncSession, clock: FakeClock, client: TestClient
) -> None:
    await project_agent_task(session, clock)
    ceo_id = (await add_ceo(session, clock)).id
    await session.commit()
    tasks_before = await count(session, Task)
    words = "Ask the demo team for the release notes, by Friday please."

    first = call(client, "order", text=words, request_id="retry-1")
    again = call(client, "order", text=words, request_id="retry-1")

    session.expire_all()
    (message,) = (await session.scalars(select(WakeupRequest))).all()
    assert (message.agent_id, message.source) == (ceo_id, WakeupSource.OWNER_MESSAGE)
    assert message_text(message.reason) == words
    assert await count(session, Task) == tasks_before
    assert (first, again) == ("Sent to the CEO.", "That was already sent to the CEO.")


async def test_answer_stores_the_words_in_a_reused_call_and_delivers_them(
    session: AsyncSession, clock: FakeClock, client: TestClient
) -> None:
    ids = await seed_busy(session, clock)
    reference = question_ref(ids["question"])

    text = call(client, "answer", reference=reference, words="Release from main.")

    session.expire_all()
    request = (await session.scalars(select(CallRequest))).one()
    assert request.text == "Release from main."
    question = await session.get_one(AgentQuestion, ids["question"])
    assert (question.status, question.answer) == (QuestionStatus.ANSWERED, "Release from main.")
    assert "Sent your answer" in text

    # A second answer inside the call window reuses the call and loses the race politely.
    again = call(client, "answer", reference=reference, words="No, from develop.")
    assert "already answered" in again
    assert await count(session, Call) == 1


async def test_answer_refuses_bad_input_without_storing_anything(
    session: AsyncSession, clock: FakeClock, client: TestClient
) -> None:
    ids = await seed_busy(session, clock)

    bad = call(client, "answer", reference="A1", words="yes")
    long = call(client, "answer", reference=question_ref(ids["question"]), words="word " * 100)
    unknown = call(client, "answer", reference="Q999", words="yes")

    for text in (bad, long, unknown):
        assert_spoken(text)
    assert "Keep the answer" in long
    assert await count(session, CallRequest) == 0
