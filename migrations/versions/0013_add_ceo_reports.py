"""add ceo reports

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-06 00:14:22.158974

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ceo_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("refs", sa.JSON(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("fk_ceo_reports_agent_id_agents"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            name=op.f("fk_ceo_reports_task_id_tasks"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ceo_reports")),
    )
    with op.batch_alter_table("ceo_reports", schema=None) as batch_op:
        batch_op.create_index("ix_ceo_reports_created_at", ["created_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("ceo_reports", schema=None) as batch_op:
        batch_op.drop_index("ix_ceo_reports_created_at")

    op.drop_table("ceo_reports")
