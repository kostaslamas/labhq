"""add chat outbox

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-03 06:35:33.121572

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_outbox",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("meeting_id", sa.Integer(), nullable=True),
        sa.Column("channel_key", sa.String(length=200), nullable=False),
        sa.Column("channel_name", sa.String(length=200), nullable=False),
        sa.Column("thread_key", sa.String(length=200), nullable=False),
        sa.Column("thread_title", sa.String(length=200), nullable=False),
        sa.Column("persona_name", sa.String(length=200), nullable=False),
        sa.Column("avatar_url", sa.String(length=500), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("adapter", sa.String(length=64), nullable=True),
        sa.Column("thread_ref", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'sent')", name=op.f("ck_chat_outbox_chat_post_status")
        ),
        sa.ForeignKeyConstraint(
            ["meeting_id"],
            ["meetings.id"],
            name=op.f("fk_chat_outbox_meeting_id_meetings"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_outbox")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_chat_outbox_idempotency_key")),
    )
    with op.batch_alter_table("chat_outbox", schema=None) as batch_op:
        batch_op.create_index("ix_chat_outbox_status_id", ["status", "id"], unique=False)
        batch_op.create_index(
            "ix_chat_outbox_thread_key_adapter", ["thread_key", "adapter"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("chat_outbox", schema=None) as batch_op:
        batch_op.drop_index("ix_chat_outbox_thread_key_adapter")
        batch_op.drop_index("ix_chat_outbox_status_id")

    op.drop_table("chat_outbox")
