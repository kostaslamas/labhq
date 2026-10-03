"""add usage readings

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-03 03:36:50.381636

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "usage_readings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("agent_kind", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=True),
        sa.Column("window", sa.String(length=32), nullable=True),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("limit_value", sa.Float(), nullable=True),
        sa.Column("resets_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("fk_usage_readings_agent_id_agents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name=op.f("fk_usage_readings_run_id_runs"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usage_readings")),
    )
    with op.batch_alter_table("usage_readings", schema=None) as batch_op:
        batch_op.create_index(
            "ix_usage_readings_agent_kind_unit_window",
            ["agent_kind", "unit", "window"],
            unique=False,
        )
        batch_op.create_index("ix_usage_readings_run_id", ["run_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("usage_readings", schema=None) as batch_op:
        batch_op.drop_index("ix_usage_readings_run_id")
        batch_op.drop_index("ix_usage_readings_agent_kind_unit_window")

    op.drop_table("usage_readings")
