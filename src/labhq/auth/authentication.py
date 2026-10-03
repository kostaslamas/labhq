"""Assertions: sign in with a passkey, and the check a step-up shares with it."""

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from labhq.auth import ceremony, challenges, credentials
from labhq.auth.errors import AuthError
from labhq.auth.origins import RelyingParty, relying_party
from labhq.auth.sessions import create_session
from labhq.auth.settings import AuthSettings
from labhq.db.models import PasskeyCredential

LOGIN_PURPOSE = "login"


async def issue_assertion_options(
    db: AsyncSession,
    settings: AuthSettings,
    now: datetime,
    rp: RelyingParty,
    *,
    purpose: str,
    session_id: int | None,
) -> dict[str, Any]:
    allowed = await credentials.active_for(db, rp.rp_id)
    if not allowed:
        raise AuthError("no_passkey", "No passkey is enrolled for this address; enroll one first.")
    options = ceremony.authentication_options(rp, allowed)
    await challenges.issue(
        db,
        challenge=options.challenge,
        purpose=purpose,
        rp_id=rp.rp_id,
        now=now,
        ttl_seconds=settings.challenge_ttl_seconds,
        session_id=session_id,
    )
    return options.public_key


async def check_assertion(
    db: AsyncSession,
    now: datetime,
    rp: RelyingParty,
    assertion: dict[str, Any],
    *,
    purpose: str,
    session_id: int | None,
) -> PasskeyCredential:
    """Spend the challenge issued for exactly this purpose, then verify the signature.

    The challenge is spent first, so an assertion that fails is never retried and one that
    passes is never replayed.
    """
    challenge = challenges.challenge_of(assertion)
    challenges.require(
        await challenges.consume(
            db,
            challenge=challenge,
            purpose=purpose,
            rp_id=rp.rp_id,
            now=now,
            session_id=session_id,
        )
    )
    credential_id = assertion.get("id")
    stored = (
        await credentials.by_credential_id(db, credential_id)
        if isinstance(credential_id, str)
        else None
    )
    if stored is None or stored.rp_id != rp.rp_id:
        raise AuthError("credential_unknown", "This passkey is not enrolled here.")
    if stored.revoked_at is not None:
        raise AuthError("credential_revoked", "This passkey has been revoked.")
    stored.sign_count = ceremony.verify_assertion(assertion, challenge, rp, stored)
    stored.last_used_at = now
    return stored


async def begin_login(
    db: AsyncSession, settings: AuthSettings, now: datetime, origin: str | None
) -> dict[str, Any]:
    rp = relying_party(origin, settings)
    return await issue_assertion_options(
        db, settings, now, rp, purpose=LOGIN_PURPOSE, session_id=None
    )


async def finish_login(
    db: AsyncSession,
    settings: AuthSettings,
    now: datetime,
    origin: str | None,
    assertion: dict[str, Any],
) -> str:
    """Verify the assertion and open a session; returns the session token."""
    rp = relying_party(origin, settings)
    stored = await check_assertion(db, now, rp, assertion, purpose=LOGIN_PURPOSE, session_id=None)
    return await create_session(db, settings, now, stored.id)
