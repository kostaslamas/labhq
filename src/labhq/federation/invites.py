"""The downstream side of pairing: `invite` prints a key once; only its hash is stored."""

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.clock import Clock
from labhq.db.models import FederationInvite
from labhq.federation.errors import FederationError, UnauthorizedError
from labhq.federation.keys import ALL_SCOPES, check_scopes, hash_key, new_key


@dataclass(frozen=True)
class Invitation:
    invite: FederationInvite
    # Shown once. It is not stored, so it cannot be shown again.
    key: str


class Invites:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], *, clock: Clock) -> None:
        self._sessions = sessions
        self._clock = clock

    async def create(self, *, label: str = "", scopes: Sequence[str] = ALL_SCOPES) -> Invitation:
        try:
            chosen = check_scopes(list(scopes))
        except ValueError as error:
            raise FederationError(str(error)) from None
        key = new_key()
        async with self._sessions() as db:
            invite = FederationInvite(
                key_hash=hash_key(key), label=label, scopes=chosen, created_at=self._clock.now()
            )
            db.add(invite)
            await db.commit()
        return Invitation(invite, key)

    async def list(self) -> list[FederationInvite]:
        async with self._sessions() as db:
            return list(await db.scalars(select(FederationInvite).order_by(FederationInvite.id)))

    async def revoke(self, invite_id: int) -> FederationInvite:
        async with self._sessions() as db:
            invite = await db.get(FederationInvite, invite_id)
            if invite is None:
                raise FederationError(f"no invite {invite_id}")
            if invite.revoked_at is None:
                invite.revoked_at = self._clock.now()
            await db.commit()
        return invite


async def revoked_locally(db: AsyncSession, key: str) -> bool:
    """True when this instance printed `key` and has since revoked it."""
    revoked_at = await db.scalar(
        select(FederationInvite.revoked_at).where(FederationInvite.key_hash == hash_key(key))
    )
    return revoked_at is not None


async def authenticate_invite(db: AsyncSession, clock: Clock, key: str | None) -> FederationInvite:
    """The invite a valid, unrevoked key belongs to: who may call this instance's A2A routes.

    Every failure is the same `UnauthorizedError`, like `authenticate` for nodes, so a caller
    cannot tell a revoked key from one that never existed. Scopes are checked per method.
    """
    if not key:
        raise UnauthorizedError("a federation key is required")
    invite = await db.scalar(
        select(FederationInvite).where(FederationInvite.key_hash == hash_key(key))
    )
    if invite is None or invite.revoked_at is not None:
        raise UnauthorizedError("the federation key is not valid for this call")
    return invite
