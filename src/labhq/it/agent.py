"""The IT agent: the head of the `it` department kind, under the CEO, in no project, read-only
(plan §2.2).

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
from labhq.departments import create_department, default_kinds
from labhq.hierarchy import IT, Hierarchy, HierarchySettings, check_reports_to
from labhq.it.settings import ItSettings
from labhq.settings import Settings


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
    chosen = hierarchy.adapter_for(IT, adapter)
    if chosen not in adapters:
        raise UnknownAdapterError(f"no adapter registered as {chosen!r}")
    ceo = await Hierarchy(sessions, clock=clock, adapters=adapters, settings=hierarchy).ensure_ceo()
    check_reports_to(IT, ceo.role)
    title = (settings or ItSettings()).title
    kind = default_kinds.get(IT)
    async with sessions() as db:
        _, agent = await create_department(
            db,
            clock,
            adapters=adapters,
            ceo=ceo,
            data_dir=Settings().data_dir,
            name=title,
            head_title=title,
            kind=kind.key,
            adapter=chosen,
        )
        await db.commit()
    return agent
