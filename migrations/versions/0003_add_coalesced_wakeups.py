"""add coalesced wakeups

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-02 11:18:48.038722

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Autogenerate does not compare CHECK constraints, so the status vocabulary is moved by hand.
STATUS_CHECK = "wakeup_status"
STATUSES_BEFORE = "status IN ('pending', 'dispatched', 'refused', 'cancelled')"
STATUSES_AFTER = "status IN ('pending', 'coalesced', 'dispatched', 'refused', 'cancelled')"


def upgrade() -> None:
    with op.batch_alter_table("wakeup_requests", schema=None) as batch_op:
        batch_op.add_column(sa.Column("coalesced_into_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            batch_op.f("fk_wakeup_requests_coalesced_into_id_wakeup_requests"),
            "wakeup_requests",
            ["coalesced_into_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.drop_constraint(batch_op.f("ck_wakeup_requests_wakeup_status"), type_="check")
        batch_op.create_check_constraint(STATUS_CHECK, sa.text(STATUSES_AFTER))


def downgrade() -> None:
    op.execute("DELETE FROM wakeup_requests WHERE status = 'coalesced'")
    with op.batch_alter_table("wakeup_requests", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("ck_wakeup_requests_wakeup_status"), type_="check")
        batch_op.create_check_constraint(STATUS_CHECK, sa.text(STATUSES_BEFORE))
        batch_op.drop_constraint(
            batch_op.f("fk_wakeup_requests_coalesced_into_id_wakeup_requests"), type_="foreignkey"
        )
        batch_op.drop_column("coalesced_into_id")
