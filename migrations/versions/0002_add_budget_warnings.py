"""add budget warnings

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-02 11:01:26.630632

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "budget_warnings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("scope_id", sa.Integer(), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("spent_micros", sa.BigInteger(), nullable=False),
        sa.Column("budget_micros", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "scope IN ('agent', 'project')", name=op.f("ck_budget_warnings_budget_scope")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_budget_warnings")),
        sa.UniqueConstraint(
            "scope",
            "scope_id",
            "period_start",
            name=op.f("uq_budget_warnings_scope_scope_id_period_start"),
        ),
    )


def downgrade() -> None:
    op.drop_table("budget_warnings")
