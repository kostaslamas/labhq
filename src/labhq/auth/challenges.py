"""Single-use challenges, stored as hashes so a database log never shows a live one.

One conditional UPDATE consumes a challenge, so two requests racing with the same assertion
cannot both win."""

import base64
import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.auth.errors import AuthError
from labhq.auth.tokens import hash_token
from labhq.db.models import WebauthnChallenge

# Rows outlive their expiry for a day, so tooling can still tell a replay from a stranger.
RETAIN = timedelta(days=1)


async def issue(
    db: AsyncSession,
    *,
    challenge: str,
    purpose: str,
    rp_id: str,
    now: datetime,
    ttl_seconds: int,
    session_id: int | None = None,
) -> WebauthnChallenge:
    await db.execute(delete(WebauthnChallenge).where(WebauthnChallenge.expires_at < now - RETAIN))
    row = WebauthnChallenge(
        challenge=hash_token(challenge),
        purpose=purpose,
        rp_id=rp_id,
        session_id=session_id,
        created_at=now,
        expires_at=now + timedelta(seconds=ttl_seconds),
    )
    db.add(row)
    await db.flush()
    return row


async def consume(
    db: AsyncSession,
    *,
    challenge: str,
    purpose: str,
    rp_id: str,
    now: datetime,
    session_id: int | None = None,
) -> bool:
    """Mark the challenge used if it is unused, unexpired and issued for exactly this."""
    owner = (
        WebauthnChallenge.session_id.is_(None)
        if session_id is None
        else WebauthnChallenge.session_id == session_id
    )
    result = await db.execute(
        update(WebauthnChallenge)
        .where(
            WebauthnChallenge.challenge == hash_token(challenge),
            WebauthnChallenge.purpose == purpose,
            WebauthnChallenge.rp_id == rp_id,
            WebauthnChallenge.used_at.is_(None),
            WebauthnChallenge.expires_at > now,
            owner,
        )
        .values(used_at=now)
        .execution_options(synchronize_session=False)
    )
    return bool(result.rowcount == 1)  # type: ignore[attr-defined]


def challenge_of(credential: dict[str, Any]) -> str:
    """The challenge the browser signed, from the credential's `clientDataJSON`."""
    try:
        raw = credential["response"]["clientDataJSON"]
        client_data = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
        value = client_data["challenge"]
    except (KeyError, TypeError, ValueError):
        raise AuthError("malformed_credential", "The credential cannot be read.") from None
    if not isinstance(value, str):
        raise AuthError("malformed_credential", "The credential cannot be read.")
    return value


def require(used: bool) -> None:
    if not used:
        raise AuthError("challenge_invalid", "The challenge is unknown, used or expired.")
