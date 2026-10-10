"""The owner starts a decision room, speaks in it and closes it from the Call Center widget."""

import httpx
from sqlalchemy import select

from labhq.adoption.state import STATE_KEY, AdoptionState
from labhq.cli.context import Context
from labhq.db.enums import ApprovalStatus, MeetingStatus
from labhq.db.models import Agent, Approval, Meeting
from tests.api.callcenter.conftest import Room, settled
from tests.meetings.conftest import Stage


async def _speakers(client: httpx.AsyncClient, room: Room) -> list[str]:
    detail = (await client.get(f"/api/meetings/{room.id}")).json()
    return [message["speaker"] for message in detail["messages"]]


async def test_a_requested_room_is_listed_with_its_cost_and_its_pending_approval(
    client: httpx.AsyncClient, room: Room
) -> None:
    [item] = (await client.get("/api/callcenter/rooms")).json()

    assert item["id"] == room.id
    assert (item["status"], item["approval_status"]) == ("requested", "pending")
    assert (item["pinned_kind"], item["pinned_id"]) == ("report", room.report_id)
    assert item["estimate_micros"] == 200_000 * 13
    assert (item["turns_used"], item["turn_cap"], item["waiting"]) == (0, 12, None)


async def test_starting_taps_the_approval_and_opens_the_room(
    client: httpx.AsyncClient, room: Room, context: Context, stage: Stage
) -> None:
    started = await client.post(f"/api/callcenter/rooms/{room.id}/start")
    await settled()

    assert started.status_code == 202, started.text
    async with context.sessions() as db:
        approval = await db.get_one(Approval, room.approval_id)
    assert (approval.status, approval.decided_by, approval.confirmation_kind) == (
        ApprovalStatus.APPROVED,
        "web:kostas",
        "tap",
    )
    assert await _speakers(client, room) == ["CEO", "Boss"]
    [item] = (await client.get("/api/callcenter/rooms")).json()
    assert (item["status"], item["turns_used"]) == ("running", 2)
    again = await client.post(f"/api/callcenter/rooms/{room.id}/start")
    assert again.status_code == 409


async def test_declining_cancels_the_room_and_nobody_is_asked(
    client: httpx.AsyncClient, room: Room, stage: Stage
) -> None:
    declined = await client.post(f"/api/callcenter/rooms/{room.id}/decline")

    assert declined.json()["status"] == "cancelled"
    assert stage.prompts == []


async def test_the_owner_speaks_and_each_agent_answers(
    client: httpx.AsyncClient, room: Room, stage: Stage
) -> None:
    await client.post(f"/api/callcenter/rooms/{room.id}/start")
    await settled()

    said = await client.post(
        f"/api/callcenter/rooms/{room.id}/messages",
        json={"text": "Make it one reviewer."},
        headers={"Idempotency-Key": "k1"},
    )
    repeated = await client.post(
        f"/api/callcenter/rooms/{room.id}/messages",
        json={"text": "Make it one reviewer."},
        headers={"Idempotency-Key": "k1"},
    )
    await settled()

    assert said.status_code == 201 and said.json()["source"] == "owner"
    assert repeated.status_code == 409
    assert (await _speakers(client, room))[-3:] == ["Owner", "CEO", "Boss"]
    assert "Make it one reviewer." in stage.turn_prompts()[-1]


async def test_a_manager_mid_step_shows_waiting_and_can_be_interrupted(
    client: httpx.AsyncClient, room: Room, context: Context, stage: Stage
) -> None:
    state = AdoptionState(
        kind="claude",
        cwd="/srv/atlas",
        repo="/srv/atlas",
        tmux_session="atlas",
        state_dir="/tmp/atlas",
        baseline="x",
        turn_open=True,
    )
    async with context.sessions() as db:
        manager = await db.get_one(Agent, room.manager_id)
        manager.config = {STATE_KEY: state.model_dump(mode="json")}
        await db.commit()
    seen: list[dict[str, object] | None] = []

    async def look(request: object) -> None:
        [item] = (await client.get("/api/callcenter/rooms")).json()
        seen.append(item["waiting"])

    stage.on_start.append(look)

    await client.post(f"/api/callcenter/rooms/{room.id}/start")
    await settled()

    assert seen[0] is None
    assert seen[1] == {
        "agent_id": room.manager_id,
        "agent_name": "Boss",
        "reason": "finishing its current step",
        "can_interrupt": True,
    }
    [item] = (await client.get("/api/callcenter/rooms")).json()
    assert item["waiting"] is None


async def test_closing_posts_what_was_decided_to_the_proposal(
    client: httpx.AsyncClient, room: Room, context: Context, stage: Stage
) -> None:
    stage.minutes.append(
        '{"decisions": ["Hire one reviewer"], "action_items": '
        f'[{{"title": "Open the role", "assignee": {room.manager_id}, "decision": 1}}]}}'
    )
    await client.post(f"/api/callcenter/rooms/{room.id}/start")
    await settled()

    closed = await client.post(f"/api/callcenter/rooms/{room.id}/close")
    await settled()

    assert closed.status_code == 202
    [decided] = (await client.get("/api/callcenter/decisions")).json()
    assert (decided["pinned_kind"], decided["pinned_id"]) == ("report", room.report_id)
    assert decided["decisions"] == ["Hire one reviewer"]
    [action] = decided["actions"]
    # Waits for the owner: nothing was assigned.
    assert (action["text"], action["approval_status"]) == ("Open the role", "pending")
    async with context.sessions() as db:
        meeting = await db.scalar(select(Meeting).where(Meeting.id == room.id))
    assert meeting is not None and meeting.status is MeetingStatus.ENDED
    late = await client.post(f"/api/callcenter/rooms/{room.id}/messages", json={"text": "late"})
    assert late.status_code == 409 and late.json()["error"]["code"] == "room_closed"


async def test_the_meetings_page_cannot_write_into_a_room(
    client: httpx.AsyncClient, room: Room
) -> None:
    response = await client.post(f"/api/meetings/{room.id}/messages", json={"text": "hi"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "room_in_call_center"


async def test_the_routes_need_the_owner(client: httpx.AsyncClient, room: Room) -> None:
    client.headers.pop("X-Test-Owner")

    for method, path in (
        ("GET", "/api/callcenter/rooms"),
        ("POST", f"/api/callcenter/rooms/{room.id}/start"),
        ("POST", f"/api/callcenter/rooms/{room.id}/close"),
        ("GET", "/api/callcenter/decisions"),
    ):
        assert (await client.request(method, path)).status_code == 401
