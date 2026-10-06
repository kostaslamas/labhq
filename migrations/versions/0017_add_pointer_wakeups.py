"""allow pointer wakeups for child reports and returned tasks

Revision ID: 0017
Revises: 0016
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0017"
down_revision: str | Sequence[str] | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = (
    "source IN ('timer', 'assignment', 'comment', 'approval_resolved', 'meeting', 'owner_message')"
)
NEW = (
    "source IN ('timer', 'assignment', 'comment', 'approval_resolved', 'meeting', 'owner_message', "
    "'child_report', 'task_returned')"
)
NAME = "ck_wakeup_requests_wakeup_source"


def upgrade() -> None:
    with op.batch_alter_table("wakeup_requests") as batch:
        batch.drop_constraint(op.f(NAME), type_="check")
        batch.create_check_constraint(op.f(NAME), NEW)


def downgrade() -> None:
    with op.batch_alter_table("wakeup_requests") as batch:
        batch.drop_constraint(op.f(NAME), type_="check")
        batch.create_check_constraint(op.f(NAME), OLD)
