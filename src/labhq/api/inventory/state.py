"""The last scan, kept in memory: a scan is cheap to repeat and the page asks for it often."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from labhq.inventory.found import FoundView
from labhq.inventory.model import Inventory, ProjectInventory, SessionState, ToolStatus
from labhq.inventory.scope import real


@dataclass
class Last:
    scanned_at: datetime | None = None
    left_out: int = 0
    session_count: int = 0
    project_count: int = 0
    folders_visited: int = 0
    capped: bool = False
    found: tuple[FoundView, ...] = ()
    inventory: Inventory | None = None
    tools: list[ToolStatus] = field(default_factory=list)

    def reset(self) -> None:
        self.__init__()  # type: ignore[misc]

    def keep(
        self, inventory: Inventory, tools: list[ToolStatus], found: tuple[FoundView, ...]
    ) -> None:
        self.scanned_at = inventory.scanned_at
        self.left_out = inventory.left_out
        self.session_count = sum(len(p.sessions) for p in inventory.projects)
        self.project_count = len(inventory.projects)
        self.folders_visited = inventory.folders_visited
        self.capped = inventory.discovery_capped
        self.found = found
        self.inventory = inventory
        self.tools = tools

    def project_at(self, path: str) -> ProjectInventory | None:
        """The scanned project whose folder is `path`, compared on the real path."""
        if self.inventory is None:
            return None
        wanted = real(Path(path))
        return next((p for p in self.inventory.projects if real(p.root) == wanted), None)


LAST = Last()


@dataclass(frozen=True)
class Counts:
    total: int
    running: int
    waiting: int
    idle: int


def counts_of(project: ProjectInventory) -> Counts:
    states = [s.state for s in project.sessions]
    return Counts(
        total=len(states),
        running=states.count(SessionState.RUNNING),
        waiting=states.count(SessionState.WAITING),
        idle=states.count(SessionState.IDLE),
    )
