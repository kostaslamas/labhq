"""add wording proposals that the owner confirms before the CEO gets them

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-06 00:12:06.024605

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "wording_proposals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("call_id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("after_request_pk", sa.Integer(), nullable=False),
        sa.Column("decided_by_request_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'rejected')",
            name=op.f("ck_wording_proposals_proposal_status"),
        ),
        sa.ForeignKeyConstraint(
            ["call_id"],
            ["calls.id"],
            name=op.f("fk_wording_proposals_call_id_calls"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["call_requests.request_id"],
            name=op.f("fk_wording_proposals_request_id_call_requests"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_wording_proposals")),
    )
    with op.batch_alter_table("wording_proposals") as batch_op:
        batch_op.create_index("ix_wording_proposals_request_id", ["request_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("wording_proposals") as batch_op:
        batch_op.drop_index("ix_wording_proposals_request_id")

    op.drop_table("wording_proposals")
