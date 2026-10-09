"""The upstream side of pairing: `add`, `list` and `revoke` for downstream nodes.

Adding a node registers it and gives the CEO a manager for it in a project. The manager's
adapter is `remote`, so the CEO delegates to it with `delegate_task` like to any manager.
Only the key's hash is kept; the key itself was printed by the downstream `invite`.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.clock import Clock
from labhq.db.enums import AgentStatus
from labhq.db.models import Agent, FederationNode
from labhq.federation.errors import FederationError, UnauthorizedError
from labhq.federation.keys import ALL_SCOPES, check_scopes, hash_key, looks_like_key
from labhq.hierarchy import MANAGER, check_reports_to, find_ceo
from labhq.work import find_project

REMOTE_ADAPTER = "remote"
# `agents.config` of a remote manager: which node its orders go to.
NODE_CONFIG_KEY = "node"


@dataclass(frozen=True)
class AddedNode:
    node: FederationNode
    manager: Agent


def default_name(url: str) -> str:
    host = urlsplit(url).hostname
    return host or url


class Nodes:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], *, clock: Clock) -> None:
        self._sessions = sessions
        self._clock = clock

    async def add(
        self,
        url: str,
        key: str,
        *,
        project: str,
        name: str | None = None,
        scopes: Sequence[str] = ALL_SCOPES,
        spend_cap_micros: int | None = None,
        a2a_url: str | None = None,
    ) -> AddedNode:
        for address in (url, a2a_url):
            if address is not None and urlsplit(address).scheme not in {"http", "https"}:
                raise FederationError(f"{address!r} is not an http or https URL")
        if not looks_like_key(key):
            raise FederationError("that is not a pairing key; print one with `federation invite`")
        if spend_cap_micros is not None and spend_cap_micros <= 0:
            raise FederationError("the spend cap must be positive")
        try:
            chosen = check_scopes(list(scopes))
        except ValueError as error:
            raise FederationError(str(error)) from None
        label = name or default_name(url)
        async with self._sessions() as db:
            if await db.scalar(select(FederationNode.id).where(FederationNode.name == label)):
                raise FederationError(f"a node named {label!r} is already registered")
            if await db.scalar(
                select(FederationNode.id).where(FederationNode.key_hash == hash_key(key))
            ):
                raise FederationError("that pairing key is already registered")
            owner = await find_project(db, project)
            ceo = await find_ceo(db)
            if ceo is None:
                raise FederationError("there is no CEO yet; create one with `labhq org ceo`")
            check_reports_to(MANAGER, ceo.role)
            taken = await db.scalar(
                select(Agent.id).where(
                    Agent.project_id == owner.id,
                    Agent.role == MANAGER,
                    Agent.status != AgentStatus.RETIRED,
                )
            )
            if taken is not None:
                raise FederationError(f"project {owner.name!r} already has manager {taken}")
            now = self._clock.now()
            node = FederationNode(
                name=label,
                url=url,
                a2a_url=a2a_url,
                key_hash=hash_key(key),
                scopes=chosen,
                spend_cap_micros=spend_cap_micros,
                created_at=now,
            )
            db.add(node)
            await db.flush()
            # The owner ran this command, so the manager starts active, unasked.
            manager = Agent(
                project_id=owner.id,
                role=MANAGER,
                title=f"{label} (remote)",
                reports_to=ceo.id,
                adapter=REMOTE_ADAPTER,
                config={NODE_CONFIG_KEY: node.id},
                status=AgentStatus.ACTIVE,
                created_at=now,
                updated_at=now,
            )
            db.add(manager)
            await db.flush()
            node.manager_agent_id = manager.id
            await db.commit()
        return AddedNode(node, manager)

    async def list(self) -> list[FederationNode]:
        async with self._sessions() as db:
            return list(await db.scalars(select(FederationNode).order_by(FederationNode.id)))

    async def revoke(self, reference: str) -> FederationNode:
        """Refuse the node's key from its next poll on; orders already queued stay."""
        async with self._sessions() as db:
            node = await find_node(db, reference)
            if node.revoked_at is None:
                node.revoked_at = self._clock.now()
            await db.commit()
        return node


async def find_node(db: AsyncSession, reference: str) -> FederationNode:
    query = select(FederationNode).where(FederationNode.name == reference)
    if reference.isdigit():
        query = select(FederationNode).where(FederationNode.id == int(reference))
    node = await db.scalar(query)
    if node is None:
        raise FederationError(f"no node {reference!r}")
    return node


async def authenticate(
    db: AsyncSession, clock: Clock, key: str | None, scope: str
) -> FederationNode:
    """The node a valid, unrevoked key belongs to, if the key holds `scope`.

    Every failure is the same `UnauthorizedError`, so a caller cannot tell a revoked key from
    one that never existed.
    """
    if not key:
        raise UnauthorizedError("a federation key is required")
    node = await db.scalar(select(FederationNode).where(FederationNode.key_hash == hash_key(key)))
    if node is None or node.revoked_at is not None or scope not in node.scopes:
        raise UnauthorizedError("the federation key is not valid for this call")
    node.last_seen_at = clock.now()
    return node
