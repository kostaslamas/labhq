"""add the A2A transport to federation: node URL, remote task and order origin

Revision ID: 0019
Revises: 0018
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | Sequence[str] | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("federation_nodes") as batch:
        batch.add_column(sa.Column("a2a_url", sa.Text(), nullable=True))
    with op.batch_alter_table("federation_orders") as batch:
        batch.add_column(sa.Column("remote_task_id", sa.String(length=100), nullable=True))
        batch.add_column(
            sa.Column("remote_state", sa.String(length=40), nullable=False, server_default="")
        )
    with op.batch_alter_table("federation_inbound") as batch:
        batch.add_column(sa.Column("invite_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            op.f("fk_federation_inbound_invite_id_federation_invites"),
            "federation_invites",
            ["invite_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("federation_inbound") as batch:
        batch.drop_constraint(
            op.f("fk_federation_inbound_invite_id_federation_invites"), type_="foreignkey"
        )
        batch.drop_column("invite_id")
    with op.batch_alter_table("federation_orders") as batch:
        batch.drop_column("remote_state")
        batch.drop_column("remote_task_id")
    with op.batch_alter_table("federation_nodes") as batch:
        batch.drop_column("a2a_url")
