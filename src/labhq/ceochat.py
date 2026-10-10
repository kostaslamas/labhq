"""The owner's direct conversation with the global CEO, backed by wakeups and run events."""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.db.enums import RunStatus, WakeupSource, WakeupStatus
from labhq.db.models import Run, RunEvent, WakeupRequest

HISTORY_TURNS = 6
HISTORY_CHARS = 12_000


@dataclass(frozen=True)
class ConversationTurn:
    id: int
    text: str
    reply: str | None
    status: str
    created_at: datetime
    # What the widget knew when the owner wrote: the page and the pinned proposal.
    context: dict[str, Any] | None = None


def message_text(reason: str) -> str:
    """The wakeup stores its input and a bounded conversation snapshot together."""
    try:
        value = json.loads(reason)
    except ValueError:
        return reason
    if isinstance(value, dict) and isinstance(text := value.get("text"), str):
        return text
    return reason


def message_context(reason: str) -> dict[str, Any] | None:
    """The structured context stored beside the owner's words, if the widget sent any."""
    try:
        value = json.loads(reason)
    except ValueError:
        return None
    context = value.get("context") if isinstance(value, dict) else None
    return context if isinstance(context, dict) else None


def message_reason(
    text: str, earlier: list[ConversationTurn], context: dict[str, Any] | None = None
) -> str:
    """Store a bounded history for UI and retries; the agent receives `text` and, when the
    owner pinned something, one line saying what (`message_prompt`)."""
    history = [
        {"owner": turn.text, "ceo": turn.reply}
        for turn in earlier[-HISTORY_TURNS:]
        if turn.status == "answered" and turn.reply
    ]
    while history and len(json.dumps(history, ensure_ascii=False)) > HISTORY_CHARS:
        history.pop(0)
    stored: dict[str, Any] = {"text": text, "history": history}
    if context:
        stored["context"] = context
    return json.dumps(stored, ensure_ascii=False)


def message_prompt(reason: str) -> str:
    """Give the CEO the owner's words; the CLI session already has its rules and history.

    Context follows the words on its own line, so the owner's text stays first and unchanged.
    """
    text = message_text(reason)
    pinned = (message_context(reason) or {}).get("pinned")
    if not isinstance(pinned, dict):
        return text
    summary = pinned.get("summary")
    line = f"[Pinned by the owner: {pinned.get('kind')} #{pinned.get('id')}"
    if isinstance(pinned.get("project_id"), int):
        line += f", project {pinned['project_id']}"
    line += f" - {summary}]" if isinstance(summary, str) and summary else "]"
    return f"{text}\n\n{line}"


async def owner_message_of_run(db: AsyncSession, run_id: int) -> str | None:
    """The owner's own words that started this run, or None if no owner message did.

    This is the one place the CEO's tools learn what the owner said. Every channel that
    delivers the owner's words verbatim (web chat, the Call Center) queues an
    `OWNER_MESSAGE` wakeup, so the words are read from that wakeup and never from the model.
    """
    request = await db.scalar(
        select(WakeupRequest).where(
            WakeupRequest.run_id == run_id,
            WakeupRequest.source == WakeupSource.OWNER_MESSAGE,
        )
    )
    return message_text(request.reason) if request is not None else None


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
                context=message_context(request.reason),
            )
        )
    return turns
