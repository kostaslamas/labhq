"""Enrollment: a one-time link, then a registration ceremony on the host the link names.

The first passkey exists only because `labhq passkey enroll` printed a link on the machine.
Later ones come from a signed-in session, which shows its own link as a QR code.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.auth import ceremony, challenges, credentials
from labhq.auth.errors import AuthError
from labhq.auth.origins import RelyingParty, relying_party
from labhq.auth.settings import AuthSettings
from labhq.auth.tokens import hash_token, new_token
from labhq.db.models import PasskeyCredential, WebauthnChallenge

LINK_PURPOSE = "enrollment_link"
REGISTER_PURPOSE = "register"
LINK_PATH = "/enroll"
DEFAULT_NAME = "Passkey"


@dataclass(frozen=True)
class EnrollmentLink:
    url: str
    expires_at: datetime


async def create_link(
    db: AsyncSession, settings: AuthSettings, now: datetime, base_url: str
) -> EnrollmentLink:
    """A link that enrolls one passkey on `base_url`'s host, once, within the setting's TTL."""
    rp = relying_party(base_url.rstrip("/"), settings)
    token = new_token()
    row = await challenges.issue(
        db,
        challenge=token,
        purpose=LINK_PURPOSE,
        rp_id=rp.rp_id,
        now=now,
        ttl_seconds=settings.enrollment_ttl_seconds,
    )
    # The token rides in the fragment, which a browser never sends: it stays out of every
    # proxy and access log.
    return EnrollmentLink(f"{rp.origin}{LINK_PATH}#{token}", row.expires_at)


async def _live_link(
    db: AsyncSession, token: str, rp: RelyingParty, now: datetime
) -> WebauthnChallenge:
    row = await db.scalar(
        select(WebauthnChallenge).where(
            WebauthnChallenge.challenge == hash_token(token),
            WebauthnChallenge.purpose == LINK_PURPOSE,
            WebauthnChallenge.rp_id == rp.rp_id,
            WebauthnChallenge.used_at.is_(None),
            WebauthnChallenge.expires_at > now,
        )
    )
    if row is None:
        raise AuthError(
            "enrollment_link_invalid", "This enrollment link is used, expired or wrong."
        )
    return row


async def begin(
    db: AsyncSession, settings: AuthSettings, now: datetime, origin: str | None, token: str
) -> dict[str, object]:
    rp = relying_party(origin, settings)
    await _live_link(db, token, rp, now)
    options = ceremony.registration_options(rp, await credentials.active_for(db, rp.rp_id))
    await challenges.issue(
        db,
        challenge=options.challenge,
        purpose=REGISTER_PURPOSE,
        rp_id=rp.rp_id,
        now=now,
        ttl_seconds=settings.challenge_ttl_seconds,
    )
    return options.public_key


async def finish(
    db: AsyncSession,
    settings: AuthSettings,
    now: datetime,
    origin: str | None,
    *,
    token: str,
    credential: dict[str, object],
    name: str,
) -> PasskeyCredential:
    """Verify the attestation, then spend the link and store the passkey together."""
    rp = relying_party(origin, settings)
    await _live_link(db, token, rp, now)
    challenge = challenges.challenge_of(credential)
    challenges.require(
        await challenges.consume(
            db, challenge=challenge, purpose=REGISTER_PURPOSE, rp_id=rp.rp_id, now=now
        )
    )
    registered = ceremony.verify_registration(credential, challenge, rp)
    spent = await db.execute(
        update(WebauthnChallenge)
        .where(
            WebauthnChallenge.challenge == hash_token(token),
            WebauthnChallenge.purpose == LINK_PURPOSE,
            WebauthnChallenge.used_at.is_(None),
            WebauthnChallenge.expires_at > now,
        )
        .values(used_at=now)
        .execution_options(synchronize_session=False)
    )
    if spent.rowcount != 1:  # type: ignore[attr-defined]
        raise AuthError(
            "enrollment_link_invalid", "This enrollment link is used, expired or wrong."
        )
    if await credentials.by_credential_id(db, registered.credential_id) is not None:
        raise AuthError("registration_invalid", "This passkey is already enrolled.")
    row = PasskeyCredential(
        credential_id=registered.credential_id,
        public_key=registered.public_key,
        sign_count=registered.sign_count,
        rp_id=rp.rp_id,
        transports=registered.transports,
        name=name.strip() or DEFAULT_NAME,
        created_at=now,
    )
    db.add(row)
    await db.flush()
    return row
