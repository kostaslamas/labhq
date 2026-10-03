"""add chat bindings

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-03 04:15:30.329004

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_bindings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("adapter", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("local_key", sa.String(length=200), nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('category', 'channel', 'thread', 'webhook')",
            name=op.f("ck_chat_bindings_chat_binding_kind"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_bindings")),
        sa.UniqueConstraint(
            "adapter", "kind", "external_id", name=op.f("uq_chat_bindings_adapter_kind_external_id")
        ),
        sa.UniqueConstraint(
            "adapter", "kind", "local_key", name=op.f("uq_chat_bindings_adapter_kind_local_key")
        ),
    )


def downgrade() -> None:
    op.drop_table("chat_bindings")
