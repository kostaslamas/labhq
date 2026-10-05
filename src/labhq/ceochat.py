"""The owner's direct conversation with the global CEO, backed by wakeups and run events."""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.db.enums import RunStatus, WakeupSource, WakeupStatus
from labhq.db.models import Run, RunEvent, WakeupRequest


@dataclass(frozen=True)
class ConversationTurn:
    id: int
    text: str
    reply: str | None
    status: str
    created_at: datetime


def message_text(reason: str) -> str:
    """The wakeup stores its input and a bounded conversation snapshot together."""
    try:
        value = json.loads(reason)
    except ValueError:
        return reason
    if isinstance(value, dict) and isinstance(text := value.get("text"), str):
        return text
    return reason


def message_reason(text: str, earlier: list[ConversationTurn]) -> str:
    """Store the message and retry metadata; history lives in the CEO session."""
    return json.dumps({"text": text}, ensure_ascii=False)


def message_prompt(reason: str) -> str:
    """Give the CEO the owner's words; the CLI session already has its rules and history."""
    return message_text(reason)


def _event_text(event: RunEvent) -> str | None:
    payload: dict[str, Any] = event.payload
    if event.kind == "final_answer":
        text = payload.get("text")
        return text.strip() if isinstance(text, str) and text.strip() else None
    if event.kind == "result":
        text = payload.get("result")
        return text.strip() if isinstance(text, str) and text.strip() else None
    if event.kind == "assistant":
        text = payload.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
        content = payload.get("content")
        if isinstance(content, list):
            parts: list[str] = [
                str(block["text"])
                for block in content
                if isinstance(block, dict) and isinstance(block.get("text"), str)
            ]
            return "\n".join(parts).strip() or None
    return None


async def _reply(db: AsyncSession, run_id: int) -> str | None:
    events = list(
        await db.scalars(select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.seq))
    )
    for kind in ("final_answer", "result"):
        for event in reversed(events):
            if event.kind == kind and (text := _event_text(event)):
                return text
    parts = [_event_text(event) for event in events if event.kind == "assistant"]
    return "\n".join(part for part in parts if part).strip() or None


async def conversation(db: AsyncSession, ceo_id: int, *, limit: int = 50) -> list[ConversationTurn]:
    requests = list(
        await db.scalars(
            select(WakeupRequest)
            .where(
                WakeupRequest.agent_id == ceo_id,
                WakeupRequest.source == WakeupSource.OWNER_MESSAGE,
            )
            .order_by(WakeupRequest.id.desc())
            .limit(limit)
        )
    )
    turns: list[ConversationTurn] = []
    for request in reversed(requests):
        run = await db.get(Run, request.run_id) if request.run_id is not None else None
        reply = await _reply(db, run.id) if run is not None else None
        if run is not None and run.status == RunStatus.SUCCEEDED:
            status = "answered" if reply else "failed"
        elif (
            run is not None
            and run.status in {RunStatus.FAILED, RunStatus.INTERRUPTED, RunStatus.TIMED_OUT}
        ) or request.status == WakeupStatus.REFUSED:
            status = "failed"
        elif run is not None and run.status == RunStatus.RUNNING:
            status = "running"
        else:
            status = "queued"
        turns.append(
            ConversationTurn(
                id=request.id,
                text=message_text(request.reason),
                reply=reply if status == "answered" else None,
                status=status,
                created_at=request.created_at,
            )
        )
    return turns
