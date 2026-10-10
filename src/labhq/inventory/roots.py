"""The owner's scan roots: validated, kept in the database, joined with the environment's.

The settings table (`program_state`) holds the list the CLI and the web UI edit, so a change
needs no dotfile and no restart. `LABHQ_INVENTORY_ROOTS` adds to it.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from labhq.clock import Clock
from labhq.db.models import ProgramState
from labhq.inventory.scope import Scope, build_scope, real
from labhq.inventory.settings import InventorySettings

KEY = "inventory_roots"
EXCLUDE_KEY = "inventory_exclude"


class RootError(ValueError):
    """The folder cannot be a scan root; the message says why."""


@dataclass(frozen=True)
class CheckedRoot:
    path: Path
    # Allowed, but the owner should know: the home folder is a very broad root.
    warning: str | None = None


def check_root(raw: str, *, home: Path | None = None) -> CheckedRoot:
    text = raw.strip()
    if not text:
        raise RootError("name a folder")
    expanded = Path(text).expanduser()
    if not expanded.is_absolute():
        raise RootError(f"{text!r} is not an absolute path")
    path = real(expanded)
    if not path.exists():
        raise RootError(f"{text!r} does not exist")
    if not path.is_dir():
        raise RootError(f"{text!r} is not a folder")
    if path.parent == path:
        raise RootError(f"{text!r} is the root of a filesystem, which is too broad")
    warning = None
    if path == real(home or Path.home()):
        warning = "this is your home folder: every project under it will be searched"
    return CheckedRoot(path, warning)


async def _load(db: AsyncSession, key: str) -> list[str]:
    row = await db.get(ProgramState, key, populate_existing=True)
    if row is None:
        return []
    try:
        value = json.loads(row.value)
    except json.JSONDecodeError:
        return []
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


async def stored_roots(db: AsyncSession) -> list[str]:
    return await _load(db, KEY)


async def stored_exclusions(db: AsyncSession) -> list[str]:
    return await _load(db, EXCLUDE_KEY)


async def _save(db: AsyncSession, clock: Clock, items: list[str], key: str = KEY) -> None:
    value = json.dumps(items)
    state = await db.get(ProgramState, key)
    if state is None:
        db.add(ProgramState(key=key, value=value, updated_at=clock.now()))
    else:
        state.value = value
        state.updated_at = clock.now()
    await db.flush()


async def set_roots(db: AsyncSession, clock: Clock, roots: list[str]) -> None:
    await _save(db, clock, roots, KEY)


async def set_exclusions(db: AsyncSession, clock: Clock, folders: list[str]) -> None:
    await _save(db, clock, folders, EXCLUDE_KEY)


async def add_root(
    db: AsyncSession, clock: Clock, raw: str, *, home: Path | None = None
) -> CheckedRoot:
    """Validate and keep a root; the caller commits. Adding one already kept changes nothing."""
    checked = check_root(raw, home=home)
    roots = await stored_roots(db)
    if str(checked.path) not in roots:
        await _save(db, clock, [*roots, str(checked.path)])
    return checked


async def remove_root(db: AsyncSession, clock: Clock, raw: str) -> bool:
    """Drop a root by the text it was given or its real path; False when it was not kept.

    A folder that is gone can still be removed: only the text is compared then.
    """
    roots = await stored_roots(db)
    wanted = {raw.strip(), str(Path(raw.strip()).expanduser()), str(real(raw.strip()))}
    kept = [root for root in roots if root not in wanted]
    if len(kept) == len(roots):
        return False
    await _save(db, clock, kept)
    return True


async def add_exclusion(db: AsyncSession, clock: Clock, raw: str) -> Path:
    """Keep a folder the scan should skip (a found project the owner is not interested in)."""
    text = raw.strip()
    path = real(Path(text).expanduser())
    if not text or not path.is_absolute() or not path.is_dir():
        raise RootError(f"{text!r} is not an existing folder")
    kept = await stored_exclusions(db)
    if str(path) not in kept:
        await _save(db, clock, [*kept, str(path)], EXCLUDE_KEY)
    return path


async def remove_exclusion(db: AsyncSession, clock: Clock, raw: str) -> bool:
    kept = await stored_exclusions(db)
    wanted = {raw.strip(), str(real(Path(raw.strip()).expanduser()))}
    left = [item for item in kept if item not in wanted]
    if len(left) == len(kept):
        return False
    await _save(db, clock, left, EXCLUDE_KEY)
    return True


def scope_of(
    settings: InventorySettings, stored: list[str], excluded: list[str] | None = None
) -> Scope:
    return build_scope([*settings.roots, *stored], [*settings.exclude, *(excluded or [])])


async def effective_scope(db: AsyncSession, settings: InventorySettings) -> Scope:
    return scope_of(settings, await stored_roots(db), await stored_exclusions(db))


def suggestion(settings: InventorySettings, *, home: Path | None = None) -> str | None:
    """The first suggested folder that exists, for onboarding to pre-fill."""
    for candidate in settings.suggested_roots:
        expanded = Path(candidate).expanduser()
        if home is not None and candidate.startswith("~"):
            expanded = home / candidate[2:]
        if expanded.is_dir():
            return str(expanded)
    return None
