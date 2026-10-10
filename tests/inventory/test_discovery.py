"""Project discovery: projects found inside the roots, by directory entries alone."""

import builtins
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.clock import FakeClock
from labhq.inventory.discovery import discover_projects
from labhq.inventory.roots import RootError, add_exclusion, effective_scope, remove_exclusion
from labhq.inventory.scope import build_scope
from labhq.inventory.settings import InventorySettings
from tests.inventory import stores_fixture as fx
from tests.inventory.conftest import Scan, make_repo


def touch(path: Path, *names: str) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    for name in names:
        (path / name).write_text("", encoding="utf-8")
    return path


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    root = tmp_path / "dev"
    (touch(root / "repo1") / ".git").mkdir()
    # A worktree or submodule keeps `.git` as a file.
    touch(root / "repo2", ".git")
    touch(root / "py", "pyproject.toml")
    touch(root / "node", "package.json")
    (touch(root / "group" / "inner") / ".git").mkdir()
    # Nested projects and submodules are not separate projects.
    (touch(root / "group" / "inner" / "sub") / ".git").mkdir()
    touch(root / "node_modules" / "pkg", "package.json")
    (touch(root / ".hidden" / "x") / ".git").mkdir()
    (touch(root / "old" / "proj") / ".git").mkdir()
    (touch(root / "deep" / "a" / "b" / "c" / "d") / ".git").mkdir()
    outside = tmp_path / "outside"
    (touch(outside / "stranger") / ".git").mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)
    return root


def names(tree: Path, **settings: object) -> set[str]:
    scope = build_scope([tree], settings.pop("exclude", []))  # type: ignore[arg-type]
    found = discover_projects(scope, InventorySettings(**settings))  # type: ignore[arg-type]
    return {str(p.root.relative_to(tree.resolve())) for p in found.projects}


def test_it_finds_exactly_the_projects_and_nothing_else(tree: Path) -> None:
    assert names(tree, exclude=[str(tree / "old")]) == {
        "repo1",
        "repo2",
        "py",
        "node",
        "group/inner",
    }


def test_markers_are_reported_per_project(tree: Path) -> None:
    scope = build_scope([tree], [])

    found = {p.root.name: p.markers for p in discover_projects(scope, InventorySettings()).projects}

    assert found["repo1"] == ("git",)
    assert found["py"] == ("Python",)
    assert found["node"] == ("Node",)


def test_the_depth_limit_holds(tree: Path) -> None:
    assert "group/inner" in names(tree, discovery_depth=2)
    assert "group/inner" not in names(tree, discovery_depth=1)
    assert "deep/a/b/c/d" not in names(tree, discovery_depth=4)
    assert "deep/a/b/c/d" in names(tree, discovery_depth=5)


def test_the_folder_cap_stops_the_walk_and_says_so(tree: Path) -> None:
    scope = build_scope([tree], [])

    capped = discover_projects(scope, InventorySettings(discovery_max_folders=3))
    complete = discover_projects(scope, InventorySettings())

    assert capped.capped and capped.folders_visited == 3
    assert not complete.capped


def test_no_file_is_opened_by_discovery_but_a_git_file(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A `.git` file is read (its first line) to tell a linked worktree from a repository.
    real_open = Path.open

    def only_git(self: Path, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        if self.name != ".git":
            raise AssertionError(f"discovery opened {self}")
        return real_open(self, *args, **kwargs)  # type: ignore[arg-type]

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("discovery opened a file")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(Path, "open", only_git)
    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setattr(Path, "read_bytes", forbidden)

    assert names(tree)


def test_a_symlink_out_of_the_root_is_never_followed(tree: Path) -> None:
    assert not any("stranger" in name or "link" in name for name in names(tree))


def test_nothing_is_found_without_a_root() -> None:
    assert discover_projects(build_scope([], []), InventorySettings()).projects == ()


def test_a_session_project_and_a_discovered_one_are_one_project(
    home: Path, tree: Path, scanner: Scan
) -> None:
    repo = make_repo(tree / "worked")
    fx.claude(home, repo)

    inventory = scanner(roots=[str(tree)], discovery_depth=1).scan()

    assert [p.root for p in inventory.projects] == [repo.resolve()]
    found = {f.root for f in inventory.found}
    assert repo.resolve() not in found
    assert tree.resolve() / "py" in found


def test_discovered_projects_count_toward_a_folder_manager(
    home: Path, tmp_path: Path, scanner: Scan
) -> None:
    for name in ("a", "b"):
        (touch(tmp_path / "games" / name) / ".git").mkdir()

    inventory = scanner(roots=[str(tmp_path)]).scan()

    assert inventory.projects == []
    assert [f.folder for f in inventory.folders] == [tmp_path.resolve() / "games"]


async def test_not_interested_keeps_an_exclusion_the_scan_then_respects(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock, tree: Path
) -> None:
    async with sessions() as db:
        await add_exclusion(db, clock, str(tree / "py"))
        await db.commit()
    async with sessions() as db:
        scope = await effective_scope(db, InventorySettings(roots=[str(tree)]))
    found = {p.root.name for p in discover_projects(scope, InventorySettings()).projects}

    assert "py" not in found and "node" in found

    async with sessions() as db:
        assert await remove_exclusion(db, clock, str(tree / "py"))
        with pytest.raises(RootError):
            await add_exclusion(db, clock, str(tree / "missing"))
