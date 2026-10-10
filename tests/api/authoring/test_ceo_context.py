"""The widget sends the pinned proposal as data; the CEO's buttons come back as data (#199)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from labhq.ceochat import message_prompt, message_text
from labhq.cli.context import Context
from labhq.db.enums import RunStatus, WakeupStatus
from labhq.db.models import CeoReport, Run, RunEvent, WakeupRequest
from tests.auth.conftest import WRITE


@pytest.fixture(autouse=True)
def available_kinds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("labhq.adapters.kinds._claude_binary", lambda: "/bin/claude")
    monkeypatch.setattr("labhq.adapters.kinds.shutil.which", lambda _: "/bin/codex")


async def _report(context: Context, text: str = "Hire a reviewer.") -> int:
    async with context.sessions() as db:
        report = CeoReport(agent_id=None, text=text, refs=[], created_at=context.clock.now())
        db.add(report)
        await db.commit()
        return report.id


def _configure_ceo(client: TestClient) -> None:
    client.put(
        "/api/org/ceo", json={"primary_kind": "claude", "backup_kind": "codex"}, headers=WRITE
    )


async def test_the_request_carries_the_pinned_proposal_id_as_structured_context(
    signed_in: TestClient, context: Context
) -> None:
    _configure_ceo(signed_in)
    report_id = await _report(context)

    sent = signed_in.post(
        "/api/org/ceo/messages",
        json={
            "text": "Not convinced. Why two?",
            "context": {
                "route": "/today",
                "pinned": {"kind": "report", "id": report_id, "options": ["approve", "show"]},
            },
        },
        headers=WRITE,
    )

    assert sent.status_code == 202, sent.text
    async with context.sessions() as db:
        request = await db.get_one(WakeupRequest, sent.json()["id"])
    # The owner's words are untouched; the pin travels beside them, read from the database.
    assert message_text(request.reason) == "Not convinced. Why two?"
    prompt = message_prompt(request.reason)
    assert prompt.startswith("Not convinced. Why two?\n\n[Pinned by the owner: report #")
    assert "Hire a reviewer." in prompt
    turn = signed_in.get("/api/org/ceo/messages").json()[0]
    assert turn["context"]["pinned"] == {
        "kind": "report",
        "id": report_id,
        "options": ["approve", "show"],
    }
    assert turn["context"]["route"] == "/today"


async def test_a_message_without_context_reaches_the_ceo_as_just_the_words(
    signed_in: TestClient, context: Context
) -> None:
    _configure_ceo(signed_in)

    sent = signed_in.post("/api/org/ceo/messages", json={"text": "Status?"}, headers=WRITE)

    async with context.sessions() as db:
        request = await db.get_one(WakeupRequest, sent.json()["id"])
    assert message_prompt(request.reason) == "Status?"
    assert signed_in.get("/api/org/ceo/messages").json()[0]["context"] is None


async def test_a_pinned_proposal_that_does_not_exist_is_refused(signed_in: TestClient) -> None:
    _configure_ceo(signed_in)

    response = signed_in.post(
        "/api/org/ceo/messages",
        json={"text": "Why?", "context": {"pinned": {"kind": "report", "id": 99}}},
        headers=WRITE,
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "proposal_not_found"


async def test_markers_at_the_end_of_a_reply_become_action_buttons(
    signed_in: TestClient, context: Context
) -> None:
    ceo_id = signed_in.put(
        "/api/org/ceo", json={"primary_kind": "claude", "backup_kind": "codex"}, headers=WRITE
    ).json()["id"]
    sent = signed_in.post("/api/org/ceo/messages", json={"text": "And now?"}, headers=WRITE)
    async with context.sessions() as db:
        request = await db.get_one(WakeupRequest, sent.json()["id"])
        now = context.clock.now()
        run = Run(
            agent_id=ceo_id,
            task_id=None,
            adapter="claude",
            status=RunStatus.SUCCEEDED,
            created_at=now,
            started_at=now,
            finished_at=now,
            heartbeat_at=now,
        )
        db.add(run)
        await db.flush()
        request.run_id = run.id
        request.status = WakeupStatus.DISPATCHED
        db.add(
            RunEvent(
                run_id=run.id,
                seq=1,
                kind="final_answer",
                payload={"text": "Approve it.\n[[approve approval:7]]\n[[show report:2]]"},
                created_at=now,
            )
        )
        await db.commit()

    [turn] = signed_in.get("/api/org/ceo/messages").json()

    assert turn["reply"] == "Approve it."
    assert turn["actions"] == [
        {"verb": "approve", "target_kind": "approval", "target_id": 7},
        {"verb": "show", "target_kind": "report", "target_id": 2},
    ]
    async with context.sessions() as db:
        assert (await db.scalar(select(RunEvent.payload).where(RunEvent.run_id == run.id)))[
            "text"
        ].endswith("[[show report:2]]")
