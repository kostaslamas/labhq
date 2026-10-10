"""The optional periodic scan: look for new projects, tell the owner once per new set.

Off unless `LABHQ_INVENTORY_AUTO_SCAN_MINUTES` is set. A pass scans with the same scope as
the owner's own scan (no model, no transcript), keeps what it found, and raises one
notification when projects appear that it has not announced yet. Announcements are at most
one a day, so projects found meanwhile wait and go out together. The projects announced and
still unresolved are what the Today page lists.
"""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq import work
from labhq.clock import Clock
from labhq.db.models import ProgramState, Project
from labhq.inventory.found import addable
from labhq.inventory.roots import stored_exclusions
from labhq.inventory.scan import SessionScanner
from labhq.inventory.scope import real
from labhq.inventory.scoped import scanner_for
from labhq.inventory.settings import InventorySettings
from labhq.notify import enqueue

KEY = "inventory_autoscan"
KIND = "inventory"
# The same set is never announced twice, and announcements are spaced by this much.
SPACING = timedelta(days=1)
LISTED = 10


@dataclass
class AutoState:
    last_run: datetime | None = None
    notified_at: datetime | None = None
    # Every path ever announced, so a project is announced once.
    seen: list[str] = field(default_factory=list)
    # Announced and not yet added, excluded or gone: what Today shows.
    pending: list[str] = field(default_factory=list)

    def dump(self) -> str:
        return json.dumps(
            {
                "last_run": self.last_run.isoformat() if self.last_run else None,
                "notified_at": self.notified_at.isoformat() if self.notified_at else None,
                "seen": self.seen,
                "pending": self.pending,
            }
        )

    @classmethod
    def load(cls, raw: str | None) -> "AutoState":
        try:
            data = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            data = {}
        if not isinstance(data, dict):
            return cls()

        def moment(key: str) -> datetime | None:
            try:
                return datetime.fromisoformat(data[key]) if data.get(key) else None
            except (ValueError, TypeError):
                return None

        def paths(key: str) -> list[str]:
            value = data.get(key)
            return [p for p in value if isinstance(p, str)] if isinstance(value, list) else []

        return cls(moment("last_run"), moment("notified_at"), paths("seen"), paths("pending"))


async def load_state(db: AsyncSession) -> AutoState:
    row = await db.get(ProgramState, KEY, populate_existing=True)
    return AutoState.load(row.value if row else None)


async def save_state(db: AsyncSession, clock: Clock, state: AutoState) -> None:
    row = await db.get(ProgramState, KEY)
    if row is None:
        db.add(ProgramState(key=KEY, value=state.dump(), updated_at=clock.now()))
    else:
        row.value = state.dump()
        row.updated_at = clock.now()


def due(state: AutoState, settings: InventorySettings, now: datetime) -> bool:
    if settings.auto_scan_minutes == 0:
        return False
    if state.last_run is None:
        return True
    return now - state.last_run >= timedelta(minutes=settings.auto_scan_minutes)


def announce(state: AutoState, found: list[str], now: datetime) -> list[str]:
    """Update `state` for a scan that found `found`; returns the paths to announce now."""
    state.pending = [p for p in state.pending if p in found]
    fresh = [p for p in found if p not in state.seen]
    if not fresh:
        return []
    if state.notified_at is not None and now - state.notified_at < SPACING:
        return []
    state.seen = [*state.seen, *fresh]
    state.pending = [*state.pending, *fresh]
    state.notified_at = now
    return fresh


def message(paths: list[str], roots: tuple[Path, ...]) -> tuple[str, str]:
    """The notification's title and body for newly found projects."""
    where = roots[0] if len(roots) == 1 else None
    count = len(paths)
    noun = "project" if count == 1 else "projects"
    place = f"in {where}" if where else f"in {len(roots)} folders"
    names = [Path(p).name for p in paths[:LISTED]]
    extra = f" and {count - LISTED} more" if count > LISTED else ""
    return f"{count} new {noun} found {place}", ", ".join(names) + extra


@dataclass(frozen=True)
class AutoScanResult:
    ran: bool
    announced: int = 0
    added: int = 0


async def add_found(db: AsyncSession, clock: Clock, paths: list[str]) -> list[str]:
    """Add each folder as a project named after it; returns the folders that were added.

    A name already taken is tried again with the parent folder's name in front. A folder that
    still cannot be added is left to the owner, who then sees it in the found list.
    """
    added: list[str] = []
    for text in paths:
        folder = Path(text)
        for name in (folder.name, f"{folder.parent.name}-{folder.name}"):
            try:
                async with db.begin_nested():
                    await work.add_project(
                        db, clock, name=name, repo=work.check_project_directory(folder), budget=None
                    )
            except work.WorkError:
                continue
            added.append(text)
            break
    return added


async def run_autoscan(
    db: AsyncSession,
    clock: Clock,
    settings: InventorySettings,
    *,
    scanner: SessionScanner | None = None,
    public_url: str | None = None,
) -> AutoScanResult:
    """One pass: scan if it is time, announce new projects. The caller commits."""
    now = clock.now()
    state = await load_state(db)
    if not due(state, settings, now):
        return AutoScanResult(ran=False)
    found_scanner = scanner or await scanner_for(db, clock, settings=settings)
    inventory = await asyncio.to_thread(found_scanner.scan)
    found = [str(f.root) for f in await addable(db, inventory)]
    state.last_run = now
    added = await add_found(db, clock, found) if settings.auto_add_projects else []
    found = [p for p in found if p not in added]
    fresh = announce(state, found, now)
    await save_state(db, clock, state)
    if fresh:
        title, body = message(fresh, inventory.roots)
        await enqueue(
            db,
            kind=KIND,
            subject="found",
            title=title,
            body=body,
            idempotency_key=f"{KIND}:found:{now.isoformat()}",
            click_url=f"{public_url}/ceo?panel=scan" if public_url else None,
            now=now,
        )
    if added:
        await enqueue(
            db,
            kind=KIND,
            subject="added",
            title=f"{len(added)} {'project' if len(added) == 1 else 'projects'} added",
            body=", ".join(Path(p).name for p in added[:LISTED]),
            idempotency_key=f"{KIND}:added:{now.isoformat()}",
            click_url=f"{public_url}/projects" if public_url else None,
            now=now,
        )
    return AutoScanResult(ran=True, announced=len(fresh), added=len(added))


async def pending_projects(db: AsyncSession) -> list[str]:
    """Announced projects still waiting: not added to labhq, not excluded, still a folder."""
    state = await load_state(db)
    if not state.pending:
        return []
    added = {real(Path(p)) for p in await db.scalars(select(Project.repo_path))}
    skipped = [real(Path(p)) for p in await stored_exclusions(db)]
    return [
        p
        for p in state.pending
        if Path(p).is_dir()
        and real(Path(p)) not in added
        and not any(real(Path(p)).is_relative_to(s) for s in skipped)
    ]
