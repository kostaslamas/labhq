"""The automatic scan: off by default, paced by its setting, one notification per new set."""

from datetime import timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.clock import FakeClock
from labhq.db.models import Notification, Project
from labhq.inventory.autoscan import pending_projects, run_autoscan
from labhq.inventory.roots import add_exclusion, add_root
from labhq.inventory.scan import SessionScanner
from labhq.inventory.settings import InventorySettings
from tests.inventory.conftest import Scan


def project(root: Path, name: str) -> Path:
    (root / name / ".git").mkdir(parents=True)
    return root / name


async def pass_(
    sessions: async_sessionmaker[AsyncSession],
    clock: FakeClock,
    scanner: SessionScanner,
    settings: InventorySettings,
) -> tuple[bool, int]:
    async with sessions() as db:
        result = await run_autoscan(db, clock, settings, scanner=scanner)
        await db.commit()
        return result.ran, result.announced


async def notifications(sessions: async_sessionmaker[AsyncSession]) -> list[Notification]:
    async with sessions() as db:
        return list(await db.scalars(select(Notification).order_by(Notification.id)))


async def test_it_is_off_by_default(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock, scanner: Scan, tmp_path: Path
) -> None:
    project(tmp_path / "dev", "a")

    ran = await pass_(sessions, clock, scanner(roots=[str(tmp_path / "dev")]), InventorySettings())

    assert ran == (False, 0)
    assert await notifications(sessions) == []


async def test_it_runs_at_its_interval_and_not_before(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock, scanner: Scan, tmp_path: Path
) -> None:
    root = tmp_path / "dev"
    project(root, "a")
    settings = InventorySettings(auto_scan_minutes=30, roots=[str(root)])
    found = scanner(roots=[str(root)])

    first = await pass_(sessions, clock, found, settings)
    clock.advance(timedelta(minutes=29))
    early = await pass_(sessions, clock, found, settings)
    clock.advance(timedelta(minutes=1))
    on_time = await pass_(sessions, clock, found, settings)

    assert first[0] and not early[0] and on_time[0]


async def test_a_new_set_is_announced_once_and_at_most_once_a_day(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock, scanner: Scan, tmp_path: Path
) -> None:
    root = tmp_path / "dev"
    project(root, "a")
    project(root, "b")
    settings = InventorySettings(auto_scan_minutes=30, roots=[str(root)])
    found = scanner(roots=[str(root)])

    announced = await pass_(sessions, clock, found, settings)
    (first,) = await notifications(sessions)
    clock.advance(timedelta(hours=1))
    same_set = await pass_(sessions, clock, found, settings)

    assert announced == (True, 2) and same_set == (True, 0)
    assert first.title == f"2 new projects found in {root.resolve()}"
    assert first.body == "a, b"

    # A project found within the day waits, then goes out on its own once the day has passed.
    project(root, "c")
    clock.advance(timedelta(hours=1))
    held = await pass_(sessions, clock, found, settings)
    assert held == (True, 0) and len(await notifications(sessions)) == 1
    clock.advance(timedelta(hours=24))
    later = await pass_(sessions, clock, found, settings)
    rows = await notifications(sessions)
    assert later == (True, 1) and [r.body for r in rows] == ["a, b", "c"]
    assert rows[1].title.startswith("1 new project found")


async def test_today_lists_what_was_announced_until_it_is_added_or_skipped(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock, scanner: Scan, tmp_path: Path
) -> None:
    root = tmp_path / "dev"
    a, b, c = (project(root, name) for name in "abc")
    settings = InventorySettings(auto_scan_minutes=30, roots=[str(root)])
    await pass_(sessions, clock, scanner(roots=[str(root)]), settings)

    async with sessions() as db:
        assert await pending_projects(db) == [str(a.resolve()), str(b.resolve()), str(c.resolve())]
        db.add(Project(name="a", repo_path=str(a), created_at=clock.now(), updated_at=clock.now()))
        await add_exclusion(db, clock, str(b))
        await db.commit()
    async with sessions() as db:
        assert await pending_projects(db) == [str(c.resolve())]


async def test_the_first_pass_after_the_roots_are_set_finds_them(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock, scanner: Scan, tmp_path: Path
) -> None:
    root = tmp_path / "dev"
    project(root, "a")
    async with sessions() as db:
        await add_root(db, clock, str(root))
        await db.commit()
    settings = InventorySettings(auto_scan_minutes=60)

    async with sessions() as db:
        result = await run_autoscan(db, clock, settings, scanner=scanner(roots=[str(root)]))
        await db.commit()

    assert (result.ran, result.announced) == (True, 1)
