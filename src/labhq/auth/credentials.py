"""Stored passkeys: lookup, listing and revocation."""

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.auth.errors import AuthError
from labhq.db.models import PasskeyCredential, WebSession


async def active_for(db: AsyncSession, rp_id: str) -> list[PasskeyCredential]:
    """Passkeys that can sign in on `rp_id`; those of another host are invisible here."""
    rows = await db.scalars(
        select(PasskeyCredential)
        .where(PasskeyCredential.rp_id == rp_id, PasskeyCredential.revoked_at.is_(None))
        .order_by(PasskeyCredential.id)
    )
    return list(rows)


async def all_credentials(db: AsyncSession) -> list[PasskeyCredential]:
    return list(await db.scalars(select(PasskeyCredential).order_by(PasskeyCredential.id)))


async def any_active(db: AsyncSession) -> bool:
    first = await db.scalar(
        select(PasskeyCredential.id).where(PasskeyCredential.revoked_at.is_(None)).limit(1)
    )
    return first is not None


async def by_credential_id(db: AsyncSession, credential_id: str) -> PasskeyCredential | None:
    return await db.scalar(
        select(PasskeyCredential).where(PasskeyCredential.credential_id == credential_id)
    )


async def revoke(db: AsyncSession, row_id: int, now: datetime) -> PasskeyCredential:
    """Revoke a passkey and end every session it opened."""
    credential = await db.get(PasskeyCredential, row_id)
    if credential is None:
        raise AuthError("credential_not_found", f"No passkey has id {row_id}.")
    if credential.revoked_at is None:
        credential.revoked_at = now
    await db.execute(
        update(WebSession).where(WebSession.credential_id == credential.id).values(revoked=True)
    )
    await db.flush()
    return credential
