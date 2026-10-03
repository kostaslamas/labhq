"""Web sessions: a random token in an HttpOnly cookie, its hash in the database."""

from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.auth.settings import AuthSettings
from labhq.auth.tokens import hash_token, new_token
from labhq.db.models import WebSession

# `last_seen_at` moves at most this often, so a burst of requests is not a burst of writes.
TOUCH_INTERVAL = timedelta(seconds=60)


async def create_session(
    db: AsyncSession, settings: AuthSettings, now: datetime, credential_id: int | None
) -> str:
    """Open a session and return the token, which is shown to the browser once."""
    token = new_token()
    db.add(
        WebSession(
            token_hash=hash_token(token),
            credential_id=credential_id,
            created_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(seconds=settings.session_absolute_seconds),
        )
    )
    await db.flush()
    return token


async def find_session(
    db: AsyncSession, settings: AuthSettings, now: datetime, token: str
) -> WebSession | None:
    """The live session for `token`; refreshes its idle clock. None when there is none."""
    session = await db.scalar(select(WebSession).where(WebSession.token_hash == hash_token(token)))
    if session is None or session.revoked or session.expires_at <= now:
        return None
    if session.last_seen_at + timedelta(seconds=settings.session_idle_seconds) <= now:
        return None
    if now - session.last_seen_at >= TOUCH_INTERVAL:
        session.last_seen_at = now
    return session


async def revoke_session(db: AsyncSession, session_id: int) -> None:
    await db.execute(update(WebSession).where(WebSession.id == session_id).values(revoked=True))
