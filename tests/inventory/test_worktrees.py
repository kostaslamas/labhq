"""A linked git worktree belongs to its main checkout: one project, never a second one."""

from pathlib import Path

from labhq.inventory.discovery import discover_projects
from labhq.inventory.scope import build_scope
from labhq.inventory.settings import InventorySettings
from labhq.inventory.worktree import main_checkout
from tests.inventory import stores_fixture as fx
from tests.inventory.conftest import Scan, git, make_repo


def add_worktree(repo: Path, folder: Path) -> Path:
    git(repo, "worktree", "add", "-q", "-b", folder.name, str(folder))
    return folder


def test_a_linked_worktree_is_recognised_and_a_submodule_style_file_is_not(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path / "dev" / "app")
    tree = add_worktree(repo, tmp_path / "dev" / "app-live")
    module = tmp_path / "dev" / "sub"
    module.mkdir()
    (module / ".git").write_text("gitdir: ../app/.git/modules/sub\n", encoding="utf-8")

    assert main_checkout(tree) == repo.resolve()
    assert main_checkout(repo) is None
    assert main_checkout(module) is None


def test_discovery_lists_the_main_checkout_and_not_its_worktrees(tmp_path: Path) -> None:
    root = tmp_path / "dev"
    repo = make_repo(root / "app")
    add_worktree(repo, root / "app-live")
    # Its own marker file would otherwise make the worktree a project.
    (root / "app-live" / "package.json").write_text("{}", encoding="utf-8")

    found = discover_projects(build_scope([root], []), InventorySettings())

    assert [p.root for p in found.projects] == [root / "app"]


def test_sessions_in_a_worktree_join_the_main_checkouts_project(
    home: Path, tmp_path: Path, scanner: Scan
) -> None:
    repo = make_repo(tmp_path / "work" / "app")
    tree = add_worktree(repo, tmp_path / "work" / "app-live")
    fx.claude(home, repo)
    fx.codex(home, tree)

    (project,) = scanner().scan().projects

    assert project.root == repo.resolve()
    assert sorted(s.tool for s in project.sessions) == ["claude-code", "codex"]
