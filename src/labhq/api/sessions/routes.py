"""The Session scan page: the folders the session inventory looks in.

Adding or removing a folder changes what labhq reads on this machine, so each needs a fresh
passkey assertion (purpose `session_scan:roots`, issued by `/auth/step-up/options`), like the
other settings. Roots set in the environment are shown but only the environment changes them.
"""

from pathlib import Path

from fastapi import APIRouter, Request
from pydantic import BaseModel

from labhq.api.channels.routes import prove
from labhq.api.deps import ClockDep, SessionDep
from labhq.api.errors import ApiError
from labhq.auth.routes import SignedIn
from labhq.inventory.roots import (
    RootError,
    add_root,
    remove_root,
    stored_roots,
    suggestion,
)
from labhq.inventory.scope import real
from labhq.inventory.settings import get_inventory_settings

router = APIRouter(prefix="/session-scan", tags=["sessions"])

PURPOSE = "session_scan:roots"


class RootOut(BaseModel):
    path: str
    # "stored" roots can be removed here; "environment" ones come from LABHQ_INVENTORY_ROOTS.
    source: str
    removable: bool


class ScanScopeOut(BaseModel):
    roots: list[RootOut]
    exclude: list[str]
    # True while no root is set: the scan then reads the whole machine.
    machine_wide: bool
    # A folder onboarding would offer; shown as a hint, never applied.
    suggestion: str | None


class RootIn(BaseModel):
    path: str
    credential: dict[str, object] | None = None


class RootAdded(BaseModel):
    scope: ScanScopeOut
    # Set when the folder is allowed but very broad (the home folder).
    warning: str | None


async def scope_out(db: SessionDep) -> ScanScopeOut:
    settings = get_inventory_settings()
    stored = await stored_roots(db)
    roots = [
        RootOut(path=str(real(Path(p))), source="environment", removable=False)
        for p in settings.roots
    ]
    seen = {r.path for r in roots}
    roots += [RootOut(path=p, source="stored", removable=True) for p in stored if p not in seen]
    return ScanScopeOut(
        roots=roots,
        exclude=list(settings.exclude),
        machine_wide=not roots,
        suggestion=suggestion(settings),
    )


@router.get("")
async def scan_scope_get(owner: SignedIn, db: SessionDep) -> ScanScopeOut:
    return await scope_out(db)


@router.post("/roots", status_code=201)
async def scan_scope_add(
    body: RootIn, request: Request, owner: SignedIn, db: SessionDep, clock: ClockDep
) -> RootAdded:
    """Add a folder. A missing folder or a filesystem root changes nothing."""
    await prove(request, db, clock, owner, PURPOSE, body.credential)
    try:
        checked = await add_root(db, clock, body.path)
    except RootError as error:
        await db.rollback()
        raise ApiError(422, "root_invalid", str(error)) from None
    await db.commit()
    return RootAdded(scope=await scope_out(db), warning=checked.warning)


@router.delete("/roots")
async def scan_scope_remove(
    body: RootIn, request: Request, owner: SignedIn, db: SessionDep, clock: ClockDep
) -> ScanScopeOut:
    await prove(request, db, clock, owner, PURPOSE, body.credential)
    if not await remove_root(db, clock, body.path):
        await db.rollback()
        raise ApiError(404, "root_not_found", "That folder is not one of the scan roots.")
    await db.commit()
    return await scope_out(db)
