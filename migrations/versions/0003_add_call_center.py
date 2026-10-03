"""add call center

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-03 05:17:11.386527

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("subject", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("click_url", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'failed')",
            name=op.f("ck_notifications_notification_status"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_notifications_idempotency_key")),
    )
    with op.batch_alter_table("notifications", schema=None) as batch_op:
        batch_op.create_index(
            "ix_notifications_status_next_attempt_at", ["status", "next_attempt_at"], unique=False
        )

    op.create_table(
        "calls",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=True),
        sa.Column("session_id", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('open', 'closed')", name=op.f("ck_calls_call_status")),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.id"], name=op.f("fk_calls_agent_id_agents"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calls")),
    )
    with op.batch_alter_table("calls", schema=None) as batch_op:
        batch_op.create_index(
            "ix_calls_status_last_activity_at", ["status", "last_activity_at"], unique=False
        )

    op.create_table(
        "agent_questions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("answer_request_id", sa.String(length=64), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'answered')", name=op.f("ck_agent_questions_question_status")
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("fk_agent_questions_agent_id_agents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            name=op.f("fk_agent_questions_task_id_tasks"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_questions")),
        sa.UniqueConstraint("fingerprint", name=op.f("uq_agent_questions_fingerprint")),
    )
    with op.batch_alter_table("agent_questions", schema=None) as batch_op:
        batch_op.create_index("ix_agent_questions_agent_id", ["agent_id"], unique=False)
        batch_op.create_index(
            "ix_agent_questions_status_created_at", ["status", "created_at"], unique=False
        )
        batch_op.create_index("ix_agent_questions_task_id", ["task_id"], unique=False)

    op.create_table(
        "call_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("call_id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reply", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'answered', 'failed', 'expired')",
            name=op.f("ck_call_requests_call_request_status"),
        ),
        sa.ForeignKeyConstraint(
            ["call_id"],
            ["calls.id"],
            name=op.f("fk_call_requests_call_id_calls"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_call_requests")),
        sa.UniqueConstraint("request_id", name=op.f("uq_call_requests_request_id")),
    )
    with op.batch_alter_table("call_requests", schema=None) as batch_op:
        batch_op.create_index(
            "ix_call_requests_call_id_status", ["call_id", "status"], unique=False
        )

    op.create_table(
        "status_updates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("fields", sa.JSON(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("fk_status_updates_agent_id_agents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            name=op.f("fk_status_updates_task_id_tasks"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_status_updates")),
    )
    with op.batch_alter_table("status_updates", schema=None) as batch_op:
        batch_op.create_index(
            "ix_status_updates_agent_id_observed_at", ["agent_id", "observed_at"], unique=False
        )
        batch_op.create_index("ix_status_updates_task_id", ["task_id"], unique=False)

    op.create_table(
        "deliveries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("call_id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("recipient_agent_id", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("interrupted", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["call_id"], ["calls.id"], name=op.f("fk_deliveries_call_id_calls"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["recipient_agent_id"],
            ["agents.id"],
            name=op.f("fk_deliveries_recipient_agent_id_agents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["call_requests.request_id"],
            name=op.f("fk_deliveries_request_id_call_requests"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deliveries")),
    )
    with op.batch_alter_table("deliveries", schema=None) as batch_op:
        batch_op.create_index("ix_deliveries_call_id", ["call_id"], unique=False)
        batch_op.create_index(
            "ix_deliveries_recipient_agent_id", ["recipient_agent_id"], unique=False
        )
        batch_op.create_index("ix_deliveries_request_id", ["request_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("deliveries", schema=None) as batch_op:
        batch_op.drop_index("ix_deliveries_request_id")
        batch_op.drop_index("ix_deliveries_recipient_agent_id")
        batch_op.drop_index("ix_deliveries_call_id")

    op.drop_table("deliveries")
    with op.batch_alter_table("status_updates", schema=None) as batch_op:
        batch_op.drop_index("ix_status_updates_task_id")
        batch_op.drop_index("ix_status_updates_agent_id_observed_at")

    op.drop_table("status_updates")
    with op.batch_alter_table("call_requests", schema=None) as batch_op:
        batch_op.drop_index("ix_call_requests_call_id_status")

    op.drop_table("call_requests")
    with op.batch_alter_table("agent_questions", schema=None) as batch_op:
        batch_op.drop_index("ix_agent_questions_task_id")
        batch_op.drop_index("ix_agent_questions_status_created_at")
        batch_op.drop_index("ix_agent_questions_agent_id")

    op.drop_table("agent_questions")
    with op.batch_alter_table("calls", schema=None) as batch_op:
        batch_op.drop_index("ix_calls_status_last_activity_at")

    op.drop_table("calls")
    with op.batch_alter_table("notifications", schema=None) as batch_op:
        batch_op.drop_index("ix_notifications_status_next_attempt_at")

    op.drop_table("notifications")
