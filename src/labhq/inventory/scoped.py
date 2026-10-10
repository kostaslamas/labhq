"""A scanner on the scope the owner has set (the database's roots and the environment's)."""

from sqlalchemy.ext.asyncio import AsyncSession

from labhq.adapters.tmux import AgentKinds, default_kinds
from labhq.clock import Clock
from labhq.inventory.roots import effective_scope
from labhq.inventory.scan import SessionScanner
from labhq.inventory.settings import InventorySettings, get_inventory_settings


async def scanner_for(
    db: AsyncSession,
    clock: Clock,
    *,
    kinds: AgentKinds = default_kinds,
    settings: InventorySettings | None = None,
) -> SessionScanner:
    settings = settings or get_inventory_settings()
    scope = await effective_scope(db, settings)
    return SessionScanner(kinds=kinds, settings=settings, scope=scope, clock=clock)
