"""The IT agent: one agent with role `it`, under the CEO, in no project, read-only (plan §2.2).

The operator creates it (`labhq it start`), like the CEO, so it starts active: asking is the
approval (plan §5, rule 4). Nothing creates it behind the operator's back, since every run it
makes costs tokens.
"""

from collections.abc import Collection

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.adapters import UnknownAdapterError
from labhq.clock import Clock
from labhq.db.enums import AgentStatus
from labhq.db.models import Agent
from labhq.guards.readonly import PERMISSION_MODE_KEY, READ_ONLY_MODE
from labhq.hierarchy import IT, Hierarchy, HierarchySettings, check_reports_to
from labhq.it.settings import ItSettings

# Plan §5, rule 2: agents that touch machines run read-only commands only.
IT_CONFIG = {PERMISSION_MODE_KEY: READ_ONLY_MODE}


async def find_it_agent(db: AsyncSession) -> Agent | None:
    query = (
        select(Agent)
        .where(Agent.role == IT, Agent.status != AgentStatus.RETIRED)
        .order_by(Agent.id)
        .limit(1)
    )
    return await db.scalar(query)


async def ensure_it_agent(
    sessions: async_sessionmaker[AsyncSession],
    clock: Clock,
    *,
    adapters: Collection[str],
    settings: ItSettings | None = None,
    hierarchy: HierarchySettings | None = None,
    adapter: str | None = None,
) -> Agent:
    """The IT agent, created on first use under the CEO (itself created if missing)."""
    async with sessions() as db:
        existing = await find_it_agent(db)
    if existing is not None:
        return existing
    hierarchy = hierarchy or HierarchySettings()
    chosen = adapter or hierarchy.org_adapter
    if chosen not in adapters:
        raise UnknownAdapterError(f"no adapter registered as {chosen!r}")
    ceo = await Hierarchy(sessions, clock=clock, adapters=adapters, settings=hierarchy).ensure_ceo()
    check_reports_to(IT, ceo.role)
    now = clock.now()
    agent = Agent(
        project_id=None,
        role=IT,
        title=(settings or ItSettings()).title,
        reports_to=ceo.id,
        adapter=chosen,
        config=dict(IT_CONFIG),
        status=AgentStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    async with sessions() as db:
        db.add(agent)
        await db.commit()
    return agent
