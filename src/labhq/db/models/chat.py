"""Chat bindings: which channel, thread or webhook on a chat service stands for a local key."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from labhq.db.base import Base, enum_column


class ChatBindingKind(StrEnum):
    CATEGORY = "category"
    CHANNEL = "channel"
    THREAD = "thread"
    WEBHOOK = "webhook"


class ChatBinding(Base):
    """One remote object a chat adapter created, so it is found again after a restart.

    Only identifiers live here. Webhook tokens are credentials and are fetched from the
    service when needed (issue #74).
    """

    __tablename__ = "chat_bindings"
    __table_args__ = (
        UniqueConstraint("adapter", "kind", "local_key"),
        # Inbound messages name the remote object, so the reverse lookup is unique too.
        UniqueConstraint("adapter", "kind", "external_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # A key of the chat adapter registry; open-ended, so not an enum.
    adapter: Mapped[str] = mapped_column(String(64))
    kind: Mapped[ChatBindingKind] = mapped_column(enum_column(ChatBindingKind, "chat_binding_kind"))
    local_key: Mapped[str] = mapped_column(String(200))
    external_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime]
