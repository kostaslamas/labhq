import httpx

from labhq.api.routes import default_routers
from labhq.cli.context import Context
from labhq.clock import FakeClock
from labhq.db.enums import MeetingStatus, TranscriptSource
from labhq.db.models import MeetingTranscriptEntry
from labhq.live.registry import default_topics

from .conftest import LONG_WORD, Seeded


async def test_the_router_is_registered_and_needs_the_owner(
    client: httpx.AsyncClient, seeded: Seeded
) -> None:
    assert any(spec.router.prefix == "/meetings" and not spec.public for spec in default_routers)
    anonymous = httpx.AsyncClient(transport=client._transport, base_url="http://test")
    assert (await anonymous.get("/api/meetings")).status_code == 401


async def test_the_list_is_newest_first_and_pages_by_cursor(
    client: httpx.AsyncClient, seeded: Seeded
) -> None:
    first = (await client.get("/api/meetings", params={"limit": 1})).json()
    assert [m["id"] for m in first["items"]] == [seeded.ended_id]
    assert first["items"][0]["project_name"] == "atlas"
    assert first["items"][0]["kind"] == "planning"
    second = (await client.get("/api/meetings", params={"cursor": first["next_cursor"]})).json()
    assert [m["id"] for m in second["items"]] == [seeded.standup_id]
    assert second["next_cursor"] is None
    assert second["items"][0]["channel"] is None


async def test_a_bad_cursor_is_refused(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/meetings", params={"cursor": "nonsense"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_cursor"


async def test_a_standup_reads_in_full_with_no_chat_adapter(
    client: httpx.AsyncClient, seeded: Seeded
) -> None:
    body = (await client.get(f"/api/meetings/{seeded.standup_id}")).json()
    assert body["channel"] is None
    assert body["agenda"] == "What is blocked?"
    assert body["status"] == MeetingStatus.RUNNING
    assert [p["name"] for p in body["participants"]] == ["Backend lead", "Worker"]
    assert [(m["speaker"], m["agent_id"]) for m in body["messages"]] == [
        ("Backend lead", seeded.lead_id),
        ("Worker", seeded.worker_id),
    ]
    assert body["messages"][0]["text"] == LONG_WORD


async def test_minutes_link_action_items_to_their_tasks(
    client: httpx.AsyncClient, seeded: Seeded
) -> None:
    body = (await client.get(f"/api/meetings/{seeded.ended_id}")).json()
    assert [d["text"] for d in body["decisions"]] == ["Ship the parser first"]
    (item,) = body["action_items"]
    assert item["task_id"] == seeded.task_id
    assert item["task_title"] == "Write parser tests"
    assert item["assignee_name"] == "Backend lead"
    assert item["decision_id"] == body["decisions"][0]["id"]


async def test_an_unknown_meeting_is_not_found(client: httpx.AsyncClient) -> None:
    for response in (
        await client.get("/api/meetings/999"),
        await client.post("/api/meetings/999/messages", json={"text": "hi"}),
    ):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "meeting_not_found"


async def test_joining_stores_the_owner_message_as_participation(
    client: httpx.AsyncClient, seeded: Seeded, context: Context
) -> None:
    response = await client.post(
        f"/api/meetings/{seeded.standup_id}/messages", json={"text": "  Prioritise login.  "}
    )
    assert response.status_code == 201
    message = response.json()
    assert (message["source"], message["speaker"], message["text"]) == (
        "owner",
        "Owner",
        "Prioritise login.",
    )
    async with context.sessions() as db:
        entry = await db.get_one(MeetingTranscriptEntry, message["id"])
        assert entry.source is TranscriptSource.OWNER
        assert entry.run_id is None
    again = (await client.get(f"/api/meetings/{seeded.standup_id}")).json()
    assert again["messages"][-1]["id"] == message["id"]
    assert [p["agent_id"] for p in again["participants"]].count(None) == 1


async def test_a_finished_meeting_takes_no_message(
    client: httpx.AsyncClient, seeded: Seeded
) -> None:
    response = await client.post(f"/api/meetings/{seeded.ended_id}/messages", json={"text": "late"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "meeting_closed"


async def test_an_empty_message_is_refused(client: httpx.AsyncClient, seeded: Seeded) -> None:
    response = await client.post(f"/api/meetings/{seeded.standup_id}/messages", json={"text": " "})
    assert response.status_code == 422


async def test_the_meetings_topic_moves_when_another_process_writes(
    context: Context, clock: FakeClock, seeded: Seeded
) -> None:
    (topic,) = [t for t in default_topics if t.name == "meetings"]

    async def watermark() -> tuple[object, ...]:
        async with context.sessions() as db:
            return tuple((await db.execute(topic.query())).one())

    before = await watermark()
    async with context.sessions() as db:
        db.add(
            MeetingTranscriptEntry(
                meeting_id=seeded.standup_id,
                source=TranscriptSource.SYSTEM,
                text="note",
                created_at=clock.now(),
            )
        )
        await db.commit()
    assert await watermark() != before
