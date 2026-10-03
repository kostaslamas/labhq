"""The chat outbox: one row per post a chat thread is owed, sent in id order by the loop."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from labhq.db.base import Base, enum_column


class ChatPostStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"


class ChatPost(Base):
    """A post rendered when its event happened, so sending it later needs nothing else.

    Rows that share a `thread_key` go to one thread. The first row sent opens it and keeps its
    id in `thread_ref`, which later rows reuse. There is no failed state: a post waits, with
    backoff, until the adapter takes it, so the backlog arrives complete and in order.
    """

    __tablename__ = "chat_outbox"
    __table_args__ = (
        Index("ix_chat_outbox_status_id", "status", "id"),
        Index("ix_chat_outbox_thread_key_adapter", "thread_key", "adapter"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # A meeting event or an incident transition is enqueued once however often it is seen.
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True)
    # What the post is (agenda, entry, minutes, incident_opened, ...); informational.
    kind: Mapped[str] = mapped_column(String(32))
    meeting_id: Mapped[int | None] = mapped_column(ForeignKey("meetings.id", ondelete="CASCADE"))
    channel_key: Mapped[str] = mapped_column(String(200))
    channel_name: Mapped[str] = mapped_column(String(200))
    thread_key: Mapped[str] = mapped_column(String(200))
    thread_title: Mapped[str] = mapped_column(String(200))
    persona_name: Mapped[str] = mapped_column(String(200))
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[ChatPostStatus] = mapped_column(
        enum_column(ChatPostStatus, "chat_post_status"), default=ChatPostStatus.PENDING
    )
    attempts: Mapped[int] = mapped_column(default=0)
    next_attempt_at: Mapped[datetime | None]
    last_error: Mapped[str | None] = mapped_column(String(500))
    # The chat adapter and thread the post went to, set once its thread is open.
    adapter: Mapped[str | None] = mapped_column(String(64))
    thread_ref: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime]
    sent_at: Mapped[datetime | None]
