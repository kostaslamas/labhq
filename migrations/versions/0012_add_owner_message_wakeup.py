"""allow direct owner messages to wake the CEO

Revision ID: 0012
Revises: 0011
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "source IN ('timer', 'assignment', 'comment', 'approval_resolved', 'meeting')"
NEW = (
    "source IN ('timer', 'assignment', 'comment', 'approval_resolved', 'meeting', 'owner_message')"
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
