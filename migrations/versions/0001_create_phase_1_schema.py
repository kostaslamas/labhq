"""create phase 1 schema

Revision ID: 0001
Revises:
Create Date: 2026-10-02 07:18:01.747151

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hosts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("address", sa.String(length=255), nullable=True),
        sa.Column("ssh_user", sa.String(length=64), nullable=True),
        sa.Column("is_local", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('unknown', 'up', 'degraded', 'down')", name=op.f("ck_hosts_host_status")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_hosts")),
        sa.UniqueConstraint("name", name=op.f("uq_hosts_name")),
    )
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("repo_path", sa.Text(), nullable=False),
        sa.Column("budget_micros", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'paused', 'archived')", name=op.f("ck_projects_project_status")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_projects")),
        sa.UniqueConstraint("name", name=op.f("uq_projects_name")),
    )
    op.create_table(
        "agents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("role", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("reports_to", sa.Integer(), nullable=True),
        sa.Column("adapter", sa.String(length=64), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("budget_micros", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending_approval', 'active', 'paused', 'retired')",
            name=op.f("ck_agents_agent_status"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_agents_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reports_to"],
            ["agents.id"],
            name=op.f("fk_agents_reports_to_agents"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agents")),
    )
    with op.batch_alter_table("agents", schema=None) as batch_op:
        batch_op.create_index("ix_agents_project_id_status", ["project_id", "status"], unique=False)
        batch_op.create_index("ix_agents_reports_to", ["reports_to"], unique=False)

    op.create_table(
        "health_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("host_id", sa.Integer(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "action IN ('notify', 'ticket')", name=op.f("ck_health_rules_health_rule_action")
        ),
        sa.ForeignKeyConstraint(
            ["host_id"],
            ["hosts.id"],
            name=op.f("fk_health_rules_host_id_hosts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_health_rules")),
    )
    with op.batch_alter_table("health_rules", schema=None) as batch_op:
        batch_op.create_index("ix_health_rules_enabled", ["enabled"], unique=False)

    op.create_table(
        "health_samples",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("host_id", sa.Integer(), nullable=False),
        sa.Column("metric", sa.String(length=128), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=True),
        sa.Column("value", sa.Double(), nullable=False),
        sa.Column("sampled_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["host_id"],
            ["hosts.id"],
            name=op.f("fk_health_samples_host_id_hosts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_health_samples")),
    )
    with op.batch_alter_table("health_samples", schema=None) as batch_op:
        batch_op.create_index(
            "ix_health_samples_host_id_metric_sampled_at",
            ["host_id", "metric", "sampled_at"],
            unique=False,
        )

    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("assignee_id", sa.Integer(), nullable=True),
        sa.Column("checkout_run_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('backlog', 'todo', 'in_progress', 'in_review', 'blocked', 'done', 'cancelled')",
            name=op.f("ck_tasks_task_status"),
        ),
        sa.ForeignKeyConstraint(
            ["assignee_id"],
            ["agents.id"],
            name=op.f("fk_tasks_assignee_id_agents"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["checkout_run_id"],
            ["runs.id"],
            name=op.f("fk_tasks_checkout_run_id_runs"),
            ondelete="SET NULL",
            use_alter=True,
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["tasks.id"], name=op.f("fk_tasks_parent_id_tasks"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_tasks_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tasks")),
    )
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.create_index(
            "ix_tasks_assignee_id_status", ["assignee_id", "status"], unique=False
        )
        batch_op.create_index("ix_tasks_checkout_run_id", ["checkout_run_id"], unique=False)
        batch_op.create_index("ix_tasks_parent_id", ["parent_id"], unique=False)
        batch_op.create_index("ix_tasks_project_id_status", ["project_id", "status"], unique=False)

    op.create_table(
        "agent_task_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("adapter", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("cwd", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("fk_agent_task_sessions_agent_id_agents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            name=op.f("fk_agent_task_sessions_task_id_tasks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_task_sessions")),
        sa.UniqueConstraint(
            "agent_id", "task_id", name=op.f("uq_agent_task_sessions_agent_id_task_id")
        ),
    )
    op.create_table(
        "approvals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("risk_class", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("requested_by_agent_id", sa.Integer(), nullable=True),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("decided_by", sa.String(length=200), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmation_kind", sa.String(length=64), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("execution", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "risk_class IN ('light', 'heavy')", name=op.f("ck_approvals_risk_class")
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'executed', 'execution_failed', 'cancelled')",
            name=op.f("ck_approvals_approval_status"),
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_agent_id"],
            ["agents.id"],
            name=op.f("fk_approvals_requested_by_agent_id_agents"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], name=op.f("fk_approvals_task_id_tasks"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approvals")),
    )
    with op.batch_alter_table("approvals", schema=None) as batch_op:
        batch_op.create_index(
            "ix_approvals_status_created_at", ["status", "created_at"], unique=False
        )
        batch_op.create_index("ix_approvals_task_id", ["task_id"], unique=False)

    op.create_table(
        "comments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("author_agent_id", sa.Integer(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("mentions", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["author_agent_id"],
            ["agents.id"],
            name=op.f("fk_comments_author_agent_id_agents"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], name=op.f("fk_comments_task_id_tasks"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_comments")),
    )
    with op.batch_alter_table("comments", schema=None) as batch_op:
        batch_op.create_index(
            "ix_comments_task_id_created_at", ["task_id", "created_at"], unique=False
        )

    op.create_table(
        "incidents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.Column("host_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('open', 'resolved')", name=op.f("ck_incidents_incident_status")
        ),
        sa.ForeignKeyConstraint(
            ["host_id"], ["hosts.id"], name=op.f("fk_incidents_host_id_hosts"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["rule_id"],
            ["health_rules.id"],
            name=op.f("fk_incidents_rule_id_health_rules"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], name=op.f("fk_incidents_task_id_tasks"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_incidents")),
    )
    with op.batch_alter_table("incidents", schema=None) as batch_op:
        batch_op.create_index("ix_incidents_status", ["status"], unique=False)
        batch_op.create_index(
            "uq_incidents_rule_id_host_id_open",
            ["rule_id", "host_id"],
            unique=True,
            sqlite_where=sa.text("status = 'open'"),
        )

    op.create_table(
        "runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("adapter", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("session_id_before", sa.String(length=128), nullable=True),
        sa.Column("session_id_after", sa.String(length=128), nullable=True),
        sa.Column("usage", sa.JSON(), nullable=True),
        sa.Column("exit", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'interrupted', 'timed_out')",
            name=op.f("ck_runs_run_status"),
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.id"], name=op.f("fk_runs_agent_id_agents"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], name=op.f("fk_runs_task_id_tasks"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runs")),
    )
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.create_index("ix_runs_agent_id_status", ["agent_id", "status"], unique=False)
        batch_op.create_index(
            "ix_runs_status_heartbeat_at", ["status", "heartbeat_at"], unique=False
        )
        batch_op.create_index("ix_runs_task_id", ["task_id"], unique=False)

    op.create_table(
        "cost_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("cost_micros", sa.BigInteger(), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_read_input_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_creation_input_tokens", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("fk_cost_events_agent_id_agents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_cost_events_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name=op.f("fk_cost_events_run_id_runs"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cost_events")),
    )
    with op.batch_alter_table("cost_events", schema=None) as batch_op:
        batch_op.create_index(
            "ix_cost_events_agent_id_created_at", ["agent_id", "created_at"], unique=False
        )
        batch_op.create_index(
            "ix_cost_events_project_id_created_at", ["project_id", "created_at"], unique=False
        )
        batch_op.create_index("ix_cost_events_run_id", ["run_id"], unique=False)

    op.create_table(
        "run_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name=op.f("fk_run_events_run_id_runs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_run_events")),
        sa.UniqueConstraint("run_id", "seq", name=op.f("uq_run_events_run_id_seq")),
    )
    op.create_table(
        "wakeup_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("coalesced_count", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source IN ('timer', 'assignment', 'comment', 'approval_resolved', 'meeting')",
            name=op.f("ck_wakeup_requests_wakeup_source"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'dispatched', 'refused', 'cancelled')",
            name=op.f("ck_wakeup_requests_wakeup_status"),
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("fk_wakeup_requests_agent_id_agents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.id"],
            name=op.f("fk_wakeup_requests_run_id_runs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            name=op.f("fk_wakeup_requests_task_id_tasks"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_wakeup_requests")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_wakeup_requests_idempotency_key")),
    )
    with op.batch_alter_table("wakeup_requests", schema=None) as batch_op:
        batch_op.create_index(
            "ix_wakeup_requests_agent_id_status", ["agent_id", "status"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("wakeup_requests", schema=None) as batch_op:
        batch_op.drop_index("ix_wakeup_requests_agent_id_status")

    op.drop_table("wakeup_requests")
    op.drop_table("run_events")
    with op.batch_alter_table("cost_events", schema=None) as batch_op:
        batch_op.drop_index("ix_cost_events_run_id")
        batch_op.drop_index("ix_cost_events_project_id_created_at")
        batch_op.drop_index("ix_cost_events_agent_id_created_at")

    op.drop_table("cost_events")
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.drop_index("ix_runs_task_id")
        batch_op.drop_index("ix_runs_status_heartbeat_at")
        batch_op.drop_index("ix_runs_agent_id_status")

    op.drop_table("runs")
    with op.batch_alter_table("incidents", schema=None) as batch_op:
        batch_op.drop_index(
            "uq_incidents_rule_id_host_id_open", sqlite_where=sa.text("status = 'open'")
        )
        batch_op.drop_index("ix_incidents_status")

    op.drop_table("incidents")
    with op.batch_alter_table("comments", schema=None) as batch_op:
        batch_op.drop_index("ix_comments_task_id_created_at")

    op.drop_table("comments")
    with op.batch_alter_table("approvals", schema=None) as batch_op:
        batch_op.drop_index("ix_approvals_task_id")
        batch_op.drop_index("ix_approvals_status_created_at")

    op.drop_table("approvals")
    op.drop_table("agent_task_sessions")
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.drop_index("ix_tasks_project_id_status")
        batch_op.drop_index("ix_tasks_parent_id")
        batch_op.drop_index("ix_tasks_checkout_run_id")
        batch_op.drop_index("ix_tasks_assignee_id_status")

    op.drop_table("tasks")
    with op.batch_alter_table("health_samples", schema=None) as batch_op:
        batch_op.drop_index("ix_health_samples_host_id_metric_sampled_at")

    op.drop_table("health_samples")
    with op.batch_alter_table("health_rules", schema=None) as batch_op:
        batch_op.drop_index("ix_health_rules_enabled")

    op.drop_table("health_rules")
    with op.batch_alter_table("agents", schema=None) as batch_op:
        batch_op.drop_index("ix_agents_reports_to")
        batch_op.drop_index("ix_agents_project_id_status")

    op.drop_table("agents")
    op.drop_table("projects")
    op.drop_table("hosts")
