"""add passkeys and web sessions

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-03 18:45:31.578625

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "passkey_credentials",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("credential_id", sa.String(length=1024), nullable=False),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column("sign_count", sa.Integer(), nullable=False),
        sa.Column("rp_id", sa.String(length=255), nullable=False),
        sa.Column("transports", sa.JSON(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_passkey_credentials")),
        sa.UniqueConstraint("credential_id", name=op.f("uq_passkey_credentials_credential_id")),
    )
    op.create_table(
        "web_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("credential_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["credential_id"],
            ["passkey_credentials.id"],
            name=op.f("fk_web_sessions_credential_id_passkey_credentials"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_web_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_web_sessions_token_hash")),
    )
    op.create_table(
        "webauthn_challenges",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("challenge", sa.String(length=128), nullable=False),
        sa.Column("purpose", sa.String(length=64), nullable=False),
        sa.Column("rp_id", sa.String(length=255), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["web_sessions.id"],
            name=op.f("fk_webauthn_challenges_session_id_web_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webauthn_challenges")),
        sa.UniqueConstraint("challenge", name=op.f("uq_webauthn_challenges_challenge")),
    )
    with op.batch_alter_table("webauthn_challenges", schema=None) as batch_op:
        batch_op.create_index("ix_webauthn_challenges_expires_at", ["expires_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("webauthn_challenges", schema=None) as batch_op:
        batch_op.drop_index("ix_webauthn_challenges_expires_at")

    op.drop_table("webauthn_challenges")
    op.drop_table("web_sessions")
    op.drop_table("passkey_credentials")
