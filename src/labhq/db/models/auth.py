"""Passkeys, web sessions and the single-use WebAuthn challenges (plan §5, §9.2)."""

from datetime import datetime

from sqlalchemy import JSON, Boolean, ForeignKey, Index, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from labhq.db.base import Base


class PasskeyCredential(Base):
    """A WebAuthn credential. It works on its relying-party id only, never on another host."""

    __tablename__ = "passkey_credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Base64url of the authenticator's credential id.
    credential_id: Mapped[str] = mapped_column(String(1024), unique=True)
    public_key: Mapped[bytes] = mapped_column(LargeBinary)
    sign_count: Mapped[int] = mapped_column(default=0)
    rp_id: Mapped[str] = mapped_column(String(255))
    transports: Mapped[list[str]] = mapped_column(JSON, default=list)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime]
    last_used_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]


class WebSession(Base):
    """A signed-in browser. Only the hash of its token is stored, never the token."""

    __tablename__ = "web_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    credential_id: Mapped[int | None] = mapped_column(
        ForeignKey("passkey_credentials.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime]
    last_seen_at: Mapped[datetime]
    expires_at: Mapped[datetime]
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class WebauthnChallenge(Base):
    """A challenge issued once, for one purpose, consumed by one conditional update.

    An enrollment link is a row too: its `challenge` is the hash of the link's token.
    """

    __tablename__ = "webauthn_challenges"
    __table_args__ = (Index("ix_webauthn_challenges_expires_at", "expires_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    challenge: Mapped[str] = mapped_column(String(128), unique=True)
    # `login`, `register`, `enrollment_link` or a step-up purpose such as `approval:42`.
    purpose: Mapped[str] = mapped_column(String(64))
    rp_id: Mapped[str] = mapped_column(String(255))
    # A step-up challenge belongs to the session that asked for it.
    session_id: Mapped[int | None] = mapped_column(ForeignKey("web_sessions.id", ondelete="CASCADE"))
    created_at: Mapped[datetime]
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]
