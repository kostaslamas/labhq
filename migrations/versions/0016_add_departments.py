"""add departments: non-code units, with tasks that belong to a project or a department

Revision ID: 0016
Revises: 0015
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | Sequence[str] | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TASK_SCOPE = (
    "(project_id IS NOT NULL AND department_id IS NULL) "
    "OR (project_id IS NULL AND department_id IS NOT NULL)"
)
SCOPE_NEW = "scope IN ('agent', 'project', 'department')"
SCOPE_OLD = "scope IN ('agent', 'project')"
SCOPE_NAME = "ck_budget_warnings_budget_scope"


def upgrade() -> None:
    op.create_table(
        "departments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("head_agent_id", sa.Integer(), nullable=True),
        sa.Column("budget_micros", sa.BigInteger(), nullable=True),
        sa.Column("folder", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "active",
                "paused",
                "archived",
                name="department_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["head_agent_id"],
            ["agents.id"],
            name=op.f("fk_departments_head_agent_id_agents"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_departments")),
        sa.UniqueConstraint("name", name=op.f("uq_departments_name")),
        sa.CheckConstraint(
            "status IN ('active', 'paused', 'archived')",
            name=op.f("ck_departments_department_status"),
        ),
    )
    with op.batch_alter_table("agents") as batch:
        batch.add_column(sa.Column("department_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            op.f("fk_agents_department_id_departments"),
            "departments",
            ["department_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_agents_department_id", ["department_id"], unique=False)
    with op.batch_alter_table("tasks") as batch:
        batch.alter_column("project_id", existing_type=sa.Integer(), nullable=True)
        batch.add_column(sa.Column("department_id", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column("deliverable", sa.String(length=32), nullable=False, server_default="branch")
        )
        batch.add_column(sa.Column("deliverable_ref", sa.Text(), nullable=True))
        batch.create_foreign_key(
            op.f("fk_tasks_department_id_departments"),
            "departments",
            ["department_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_index(
            "ix_tasks_department_id_status", ["department_id", "status"], unique=False
        )
        batch.create_check_constraint(op.f("ck_tasks_task_scope"), TASK_SCOPE)
    with op.batch_alter_table("budget_warnings") as batch:
        batch.drop_constraint(op.f(SCOPE_NAME), type_="check")
        batch.create_check_constraint(op.f(SCOPE_NAME), SCOPE_NEW)


def downgrade() -> None:
    with op.batch_alter_table("budget_warnings") as batch:
        batch.drop_constraint(op.f(SCOPE_NAME), type_="check")
        batch.create_check_constraint(op.f(SCOPE_NAME), SCOPE_OLD)
    with op.batch_alter_table("tasks") as batch:
        batch.drop_constraint(op.f("ck_tasks_task_scope"), type_="check")
        batch.drop_index("ix_tasks_department_id_status")
        batch.drop_constraint(op.f("fk_tasks_department_id_departments"), type_="foreignkey")
        batch.drop_column("deliverable_ref")
        batch.drop_column("deliverable")
        batch.drop_column("department_id")
        batch.alter_column("project_id", existing_type=sa.Integer(), nullable=False)
    with op.batch_alter_table("agents") as batch:
        batch.drop_index("ix_agents_department_id")
        batch.drop_constraint(op.f("fk_agents_department_id_departments"), type_="foreignkey")
        batch.drop_column("department_id")
    op.drop_table("departments")
