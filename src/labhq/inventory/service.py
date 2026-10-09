"""The scan as the CEO and the Call Center use it: scan, report to the CEO, speak."""

import asyncio
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from labhq.adapters.tmux import AgentKinds, default_kinds
from labhq.clock import Clock
from labhq.hierarchy import find_ceo
from labhq.inventory.analysis import AnalysisError, find_project
from labhq.inventory.login import StatusRunner, run_status, tool_statuses
from labhq.inventory.model import Inventory, ProjectInventory, SessionInfo, ToolStatus
from labhq.inventory.report import report_to_ceo, spoken
from labhq.inventory.scan import SessionScanner
from labhq.inventory.settings import InventorySettings, get_inventory_settings


@dataclass(frozen=True)
class ScanResult:
    inventory: Inventory
    tools: list[ToolStatus]
    report_ids: list[int]

    @property
    def text(self) -> str:
        return spoken(self.inventory)


async def scan_and_report(
    db: AsyncSession,
    clock: Clock,
    *,
    scanner: SessionScanner | None = None,
    kinds: AgentKinds = default_kinds,
    settings: InventorySettings | None = None,
    run: StatusRunner = run_status,
    report: bool = True,
) -> ScanResult:
    """Scan without a model, then give the CEO one report per project. The caller commits."""
    settings = settings or get_inventory_settings()
    found = scanner or SessionScanner(kinds=kinds, settings=settings, clock=clock)
    inventory = await asyncio.to_thread(found.scan)
    tools = await tool_statuses(db, kinds, clock, settings, run=run)
    ids: list[int] = []
    if report:
        ceo = await find_ceo(db)
        ids = await report_to_ceo(db, clock, inventory, tools, ceo_id=ceo.id if ceo else None)
    return ScanResult(inventory, tools, ids)


def locate(
    inventory: Inventory, project: str, *, session_id: str | None = None, pid: int | None = None
) -> tuple[ProjectInventory, SessionInfo]:
    """The one session a command names, by its id or its process id, in a project."""
    chosen = find_project(inventory.projects, project)
    matches = [
        s
        for s in chosen.sessions
        if (pid is not None and s.pid == pid)
        or (session_id is not None and s.session_id == session_id)
    ]
    if len(matches) != 1:
        raise AnalysisError(f"name exactly one session of {chosen.name}; found {len(matches)}")
    return chosen, matches[0]
