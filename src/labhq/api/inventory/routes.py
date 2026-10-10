"""The scan folders and the projects found in them.

Changing the folders or the exclusions changes what labhq reads on this machine, so each needs
a fresh passkey assertion (purpose `session_scan:roots`, issued by `/auth/step-up/options`),
like the other settings. Roots and exclusions set in the environment are shown but only the
environment changes them. The last scan is kept in memory: it is cheap to repeat.
"""

import asyncio
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request
from pydantic import BaseModel

from labhq.api.channels.routes import prove
from labhq.api.deps import ClockDep, SessionDep
from labhq.api.errors import ApiError
from labhq.api.inventory.state import LAST
from labhq.auth.routes import SignedIn
from labhq.inventory.found import not_yet_added, view
from labhq.inventory.login import run_status
from labhq.inventory.roots import (
    RootError,
    add_exclusion,
    check_root,
    set_exclusions,
    set_roots,
    stored_exclusions,
    stored_roots,
    suggestion,
)
from labhq.inventory.scope import real
from labhq.inventory.scoped import scanner_for
from labhq.inventory.service import scan_and_report
from labhq.inventory.settings import get_inventory_settings

router = APIRouter(prefix="/inventory", tags=["inventory"])

PURPOSE = "session_scan:roots"
# Runs a tool's own status command; the tests swap it so no real CLI is started.
status_runner = run_status


class FolderOut(BaseModel):
    path: str
    # "environment" ones come from LABHQ_INVENTORY_ROOTS / _EXCLUDE and are not edited here.
    source: str
    removable: bool


class FoundOut(BaseModel):
    path: str
    name: str
    relative: str
    markers: list[str]
    last_commit_at: datetime | None


class ScanOut(BaseModel):
    # None until a scan has run since labhq started.
    scanned_at: datetime | None
    left_out: int
    session_count: int
    project_count: int
    folders_visited: int
    # True when the folder cap stopped the discovery walk.
    capped: bool
    found: list[FoundOut]


class ScopeOut(BaseModel):
    roots: list[FolderOut]
    exclude: list[FolderOut]
    machine_wide: bool
    # A folder onboarding would offer; shown as a hint, never applied.
    suggestion: str | None
    scan: ScanOut


class ScopeIn(BaseModel):
    """The stored lists, whole: what the page shows minus the environment's entries."""

    roots: list[str]
    exclude: list[str] = []
    credential: dict[str, object] | None = None


class ScopeSaved(BaseModel):
    scope: ScopeOut
    # The home folder is allowed but very broad.
    warnings: list[str]


class ExclusionIn(BaseModel):
    path: str
    credential: dict[str, object] | None = None


def scan_out() -> ScanOut:
    return ScanOut(
        scanned_at=LAST.scanned_at,
        left_out=LAST.left_out,
        session_count=LAST.session_count,
        project_count=LAST.project_count,
        folders_visited=LAST.folders_visited,
        capped=LAST.capped,
        found=[
            FoundOut(
                path=f.path,
                name=f.name,
                relative=f.relative,
                markers=list(f.markers),
                last_commit_at=f.last_commit_at,
            )
            for f in LAST.found
        ],
    )


async def scope_out(db: SessionDep) -> ScopeOut:
    settings = get_inventory_settings()
    stored, excluded = await stored_roots(db), await stored_exclusions(db)
    env_roots = [str(real(Path(p))) for p in settings.roots]
    env_exclude = [str(Path(p).expanduser()) for p in settings.exclude]
    roots = [FolderOut(path=p, source="environment", removable=False) for p in env_roots]
    roots += [
        FolderOut(path=p, source="stored", removable=True) for p in stored if p not in env_roots
    ]
    exclude = [FolderOut(path=p, source="environment", removable=False) for p in env_exclude]
    exclude += [
        FolderOut(path=p, source="stored", removable=True) for p in excluded if p not in env_exclude
    ]
    return ScopeOut(
        roots=roots,
        exclude=exclude,
        machine_wide=not roots,
        suggestion=suggestion(settings),
        scan=scan_out(),
    )


@router.get("/roots")
async def roots_get(owner: SignedIn, db: SessionDep) -> ScopeOut:
    return await scope_out(db)


@router.put("/roots")
async def roots_put(
    body: ScopeIn, request: Request, owner: SignedIn, db: SessionDep, clock: ClockDep
) -> ScopeSaved:
    """Replace the stored roots and exclusions. One that cannot be used changes nothing."""
    await prove(request, db, clock, owner, PURPOSE, body.credential)
    warnings: list[str] = []
    try:
        roots = []
        for raw in body.roots:
            checked = check_root(raw)
            roots.append(str(checked.path))
            if checked.warning:
                warnings.append(checked.warning)
        exclude = []
        for raw in body.exclude:
            path = real(Path(raw.strip()).expanduser())
            if not path.is_absolute() or not path.is_dir():
                raise RootError(f"{raw!r} is not an existing folder")
            exclude.append(str(path))
    except RootError as error:
        await db.rollback()
        raise ApiError(422, "root_invalid", str(error)) from None
    await set_roots(db, clock, list(dict.fromkeys(roots)))
    await set_exclusions(db, clock, list(dict.fromkeys(exclude)))
    await db.commit()
    return ScopeSaved(scope=await scope_out(db), warnings=warnings)


@router.post("/exclusions", status_code=201)
async def exclusions_add(
    body: ExclusionIn, request: Request, owner: SignedIn, db: SessionDep, clock: ClockDep
) -> ScopeOut:
    """ "Not interested" in a found project: the scan skips that folder from now on."""
    await prove(request, db, clock, owner, PURPOSE, body.credential)
    try:
        path = await add_exclusion(db, clock, body.path)
    except RootError as error:
        await db.rollback()
        raise ApiError(422, "root_invalid", str(error)) from None
    await db.commit()
    LAST.found = tuple(f for f in LAST.found if not real(Path(f.path)).is_relative_to(path))
    return await scope_out(db)


@router.get("/scan")
async def scan_get(owner: SignedIn) -> ScanOut:
    return scan_out()


@router.post("/scan")
async def scan_now(owner: SignedIn, db: SessionDep, clock: ClockDep) -> ScanOut:
    """Scan now: sessions and projects in the roots. No model is called, no transcript read."""
    settings = get_inventory_settings()
    scanner = await scanner_for(db, clock, settings=settings)
    result = await scan_and_report(
        db, clock, scanner=scanner, settings=settings, report=False, run=status_runner
    )
    found = await not_yet_added(db, result.inventory.found)
    views = await asyncio.to_thread(
        lambda: tuple(view(f, timeout=settings.command_timeout_seconds) for f in found)
    )
    LAST.keep(result.inventory, result.tools, views)
    return scan_out()
