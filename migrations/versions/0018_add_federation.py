"""add federation: remote nodes, orders and reports, and the upstream order wakeup

Revision ID: 0018
Revises: 0017
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | Sequence[str] | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

WAKEUP_OLD = (
    "source IN ('timer', 'assignment', 'comment', 'approval_resolved', 'meeting', 'owner_message', "
    "'child_report', 'task_returned')"
)
WAKEUP_NEW = (
    "source IN ('timer', 'assignment', 'comment', 'approval_resolved', 'meeting', 'owner_message', "
    "'child_report', 'task_returned', 'upstream_order')"
)
WAKEUP_NAME = "ck_wakeup_requests_wakeup_source"


def _wakeup_check(expression: str) -> None:
    with op.batch_alter_table("wakeup_requests") as batch:
        batch.drop_constraint(op.f(WAKEUP_NAME), type_="check")
        batch.create_check_constraint(op.f(WAKEUP_NAME), expression)


def upgrade() -> None:
    _wakeup_check(WAKEUP_NEW)
    op.create_table(
        "federation_inbound",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("upstream_order_id", sa.Integer(), nullable=False),
        sa.Column("upstream_name", sa.String(length=100), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("spend_cap_micros", sa.BigInteger(), nullable=True),
        sa.Column("task_ids", sa.JSON(), nullable=False),
        sa.Column("report_seq", sa.Integer(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_federation_inbound")),
        sa.UniqueConstraint(
            "upstream_order_id", name=op.f("uq_federation_inbound_upstream_order_id")
        ),
    )
    op.create_table(
        "federation_invites",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_federation_invites")),
        sa.UniqueConstraint("key_hash", name=op.f("uq_federation_invites_key_hash")),
    )
    op.create_table(
        "federation_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("inbound_id", sa.Integer(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("ref", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('progress', 'ready', 'blocked')", name="federation_report_status"
        ),
        sa.CheckConstraint(
            "status IN ('progress', 'ready', 'blocked')",
            name=op.f("ck_federation_reports_federation_report_status"),
        ),
        sa.ForeignKeyConstraint(
            ["inbound_id"],
            ["federation_inbound.id"],
            name=op.f("fk_federation_reports_inbound_id_federation_inbound"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_federation_reports")),
        sa.UniqueConstraint("inbound_id", "seq", name="uq_federation_reports_inbound_id_seq"),
    )
    with op.batch_alter_table("federation_reports", schema=None) as batch_op:
        batch_op.create_index("ix_federation_reports_delivered_at", ["delivered_at"], unique=False)

    op.create_table(
        "federation_nodes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("manager_agent_id", sa.Integer(), nullable=True),
        sa.Column("spend_cap_micros", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["manager_agent_id"],
            ["agents.id"],
            name=op.f("fk_federation_nodes_manager_agent_id_agents"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_federation_nodes")),
        sa.UniqueConstraint("key_hash", name=op.f("uq_federation_nodes_key_hash")),
        sa.UniqueConstraint("name", name=op.f("uq_federation_nodes_name")),
    )
    op.create_table(
        "federation_orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("node_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("spend_cap_micros", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("report_seq", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'delivered', 'acknowledged')", name="federation_order_status"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'delivered', 'acknowledged')",
            name=op.f("ck_federation_orders_federation_order_status"),
        ),
        sa.ForeignKeyConstraint(
            ["node_id"],
            ["federation_nodes.id"],
            name=op.f("fk_federation_orders_node_id_federation_nodes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.id"],
            name=op.f("fk_federation_orders_run_id_runs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            name=op.f("fk_federation_orders_task_id_tasks"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_federation_orders")),
        sa.UniqueConstraint("run_id", name="uq_federation_orders_run_id"),
    )
    with op.batch_alter_table("federation_orders", schema=None) as batch_op:
        batch_op.create_index(
            "ix_federation_orders_node_id_status", ["node_id", "status"], unique=False
        )


def downgrade() -> None:
    _wakeup_check(WAKEUP_OLD)
    with op.batch_alter_table("federation_orders", schema=None) as batch_op:
        batch_op.drop_index("ix_federation_orders_node_id_status")

    op.drop_table("federation_orders")
    op.drop_table("federation_nodes")
    with op.batch_alter_table("federation_reports", schema=None) as batch_op:
        batch_op.drop_index("ix_federation_reports_delivered_at")

    op.drop_table("federation_reports")
    op.drop_table("federation_invites")
    op.drop_table("federation_inbound")
