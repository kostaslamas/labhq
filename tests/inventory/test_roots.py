"""Scan roots: what may be a root, and that the list lives in the settings table."""

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.clock import FakeClock
from labhq.inventory.roots import (
    RootError,
    add_root,
    check_root,
    effective_scope,
    remove_root,
    stored_roots,
    suggestion,
)
from labhq.inventory.settings import InventorySettings


def test_a_missing_folder_a_file_and_a_relative_path_are_refused(tmp_path: Path) -> None:
    (tmp_path / "file").write_text("x", encoding="utf-8")

    for bad, reason in (
        (tmp_path / "nope", "does not exist"),
        (tmp_path / "file", "not a folder"),
        ("relative/dir", "not an absolute path"),
        ("  ", "name a folder"),
    ):
        with pytest.raises(RootError, match=reason):
            check_root(str(bad))


def test_the_filesystem_root_is_refused(tmp_path: Path) -> None:
    with pytest.raises(RootError, match="root of a filesystem"):
        check_root("/")
    with pytest.raises(RootError, match="root of a filesystem"):
        check_root(tmp_path.anchor)


def test_the_home_folder_is_allowed_with_a_warning(tmp_path: Path) -> None:
    broad = check_root(str(tmp_path), home=tmp_path)
    narrow = check_root(str(tmp_path), home=tmp_path / "else")

    assert broad.path == tmp_path.resolve() and broad.warning is not None
    assert "home folder" in broad.warning
    assert narrow.warning is None


def test_a_root_is_kept_as_its_real_path(tmp_path: Path) -> None:
    target = tmp_path / "real"
    target.mkdir()
    (tmp_path / "alias").symlink_to(target, target_is_directory=True)

    assert check_root(str(tmp_path / "alias" / ".." / "real")).path == target.resolve()


async def test_roots_persist_in_the_settings_table_and_join_the_environment(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock, tmp_path: Path
) -> None:
    mine, env = tmp_path / "mine", tmp_path / "env"
    mine.mkdir()
    env.mkdir()

    async with sessions() as db:
        await add_root(db, clock, str(mine))
        await add_root(db, clock, str(mine))  # twice: still one
        await db.commit()
    async with sessions() as db:
        assert await stored_roots(db) == [str(mine.resolve())]
        scope = await effective_scope(db, InventorySettings(roots=[str(env)]))
        assert scope.roots == (env.resolve(), mine.resolve())
        assert await remove_root(db, clock, str(mine))
        assert not await remove_root(db, clock, str(mine))
        await db.commit()
    async with sessions() as db:
        assert (await effective_scope(db, InventorySettings())).machine_wide


async def test_a_root_whose_folder_is_gone_can_still_be_removed(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock, tmp_path: Path
) -> None:
    gone = tmp_path / "gone"
    gone.mkdir()
    async with sessions() as db:
        await add_root(db, clock, str(gone))
        await db.commit()
    gone.rmdir()
    async with sessions() as db:
        assert await remove_root(db, clock, str(gone))


def test_the_suggestion_is_the_first_existing_candidate(tmp_path: Path) -> None:
    (tmp_path / "code").mkdir()
    (tmp_path / "src").mkdir()
    settings = InventorySettings()

    assert suggestion(settings, home=tmp_path) == str(tmp_path / "code")
    assert suggestion(settings, home=tmp_path / "empty") is None
