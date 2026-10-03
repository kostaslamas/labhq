"""Write side of the chat outbox: a rendered post per meeting event or incident transition.

Rows are rendered when the event happens and inserted once per idempotency key, so a listener
that fires twice, or an incident seen on every pass, still owes the thread one post.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.chat import Persona
from labhq.meetings.channels.models import ChatPost, ChatPostStatus


@dataclass(frozen=True)
class Destination:
    """The channel and thread a post belongs to."""

    channel_key: str
    channel_name: str
    thread_key: str
    thread_title: str


async def enqueue(
    db: AsyncSession,
    *,
    key: str,
    kind: str,
    destination: Destination,
    persona: Persona,
    text: str,
    now: datetime,
    meeting_id: int | None = None,
) -> bool:
    """Add a pending post in the caller's transaction; False when `key` was already queued."""
    statement = (
        insert(ChatPost)
        .values(
            idempotency_key=key,
            kind=kind,
            meeting_id=meeting_id,
            channel_key=destination.channel_key,
            channel_name=destination.channel_name[:200],
            thread_key=destination.thread_key,
            thread_title=destination.thread_title[:200],
            persona_name=persona.name[:200],
            avatar_url=persona.avatar_url,
            text=text,
            status=ChatPostStatus.PENDING,
            attempts=0,
            created_at=now,
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
        .returning(ChatPost.id)
    )
    return await db.scalar(statement) is not None
