"""add meetings

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-03 04:10:03.556127

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "meetings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("agenda", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("end_reason", sa.String(length=64), nullable=True),
        sa.Column("channel_adapter", sa.String(length=64), nullable=True),
        sa.Column("external_ref", sa.String(length=255), nullable=True),
        sa.Column("facilitator_agent_id", sa.Integer(), nullable=True),
        sa.Column("approval_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('requested', 'running', 'ended', 'failed', 'cancelled')",
            name=op.f("ck_meetings_meeting_status"),
        ),
        sa.ForeignKeyConstraint(
            ["approval_id"],
            ["approvals.id"],
            name=op.f("fk_meetings_approval_id_approvals"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["facilitator_agent_id"],
            ["agents.id"],
            name=op.f("fk_meetings_facilitator_agent_id_agents"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_meetings_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_meetings")),
    )
    with op.batch_alter_table("meetings", schema=None) as batch_op:
        batch_op.create_index(
            "ix_meetings_project_id_kind_created_at",
            ["project_id", "kind", "created_at"],
            unique=False,
        )
        batch_op.create_index("ix_meetings_status", ["status"], unique=False)

    op.create_table(
        "meeting_decisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("meeting_id", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["meeting_id"],
            ["meetings.id"],
            name=op.f("fk_meeting_decisions_meeting_id_meetings"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_meeting_decisions")),
        sa.UniqueConstraint(
            "meeting_id", "position", name=op.f("uq_meeting_decisions_meeting_id_position")
        ),
    )
    op.create_table(
        "meeting_participants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("meeting_id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=True),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("fk_meeting_participants_agent_id_agents"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["meeting_id"],
            ["meetings.id"],
            name=op.f("fk_meeting_participants_meeting_id_meetings"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_meeting_participants")),
        sa.UniqueConstraint(
            "meeting_id", "agent_id", name=op.f("uq_meeting_participants_meeting_id_agent_id")
        ),
    )
    op.create_table(
        "meeting_action_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("meeting_id", sa.Integer(), nullable=False),
        sa.Column("decision_id", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("assignee_agent_id", sa.Integer(), nullable=True),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["assignee_agent_id"],
            ["agents.id"],
            name=op.f("fk_meeting_action_items_assignee_agent_id_agents"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["decision_id"],
            ["meeting_decisions.id"],
            name=op.f("fk_meeting_action_items_decision_id_meeting_decisions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["meeting_id"],
            ["meetings.id"],
            name=op.f("fk_meeting_action_items_meeting_id_meetings"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            name=op.f("fk_meeting_action_items_task_id_tasks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_meeting_action_items")),
        sa.UniqueConstraint("task_id", name=op.f("uq_meeting_action_items_task_id")),
    )
    with op.batch_alter_table("meeting_action_items", schema=None) as batch_op:
        batch_op.create_index("ix_meeting_action_items_meeting_id", ["meeting_id"], unique=False)

    op.create_table(
        "meeting_transcript_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("meeting_id", sa.Integer(), nullable=False),
        sa.Column("participant_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("external_ref", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source IN ('agent', 'owner', 'system')",
            name=op.f("ck_meeting_transcript_entries_transcript_source"),
        ),
        sa.ForeignKeyConstraint(
            ["meeting_id"],
            ["meetings.id"],
            name=op.f("fk_meeting_transcript_entries_meeting_id_meetings"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["participant_id"],
            ["meeting_participants.id"],
            name=op.f("fk_meeting_transcript_entries_participant_id_meeting_participants"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.id"],
            name=op.f("fk_meeting_transcript_entries_run_id_runs"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_meeting_transcript_entries")),
        sa.UniqueConstraint(
            "meeting_id",
            "external_ref",
            name=op.f("uq_meeting_transcript_entries_meeting_id_external_ref"),
        ),
    )
    with op.batch_alter_table("meeting_transcript_entries", schema=None) as batch_op:
        batch_op.create_index(
            "ix_meeting_transcript_entries_meeting_id_id", ["meeting_id", "id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("meeting_transcript_entries", schema=None) as batch_op:
        batch_op.drop_index("ix_meeting_transcript_entries_meeting_id_id")

    op.drop_table("meeting_transcript_entries")
    with op.batch_alter_table("meeting_action_items", schema=None) as batch_op:
        batch_op.drop_index("ix_meeting_action_items_meeting_id")

    op.drop_table("meeting_action_items")
    op.drop_table("meeting_participants")
    op.drop_table("meeting_decisions")
    with op.batch_alter_table("meetings", schema=None) as batch_op:
        batch_op.drop_index("ix_meetings_status")
        batch_op.drop_index("ix_meetings_project_id_kind_created_at")

    op.drop_table("meetings")
