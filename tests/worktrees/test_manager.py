from pathlib import Path

import pytest

from labhq.settings import Settings
from labhq.worktrees import WorktreeError, Worktrees, branch_name, default_root
from labhq.worktrees.git import GitError, run_git
from tests.worktrees.gitrepo import commit_file, head


@pytest.fixture
def worktrees(repo: Path, tmp_path: Path) -> Worktrees:
    return Worktrees(repo, tmp_path / "data" / "worktrees")


def test_a_task_gets_its_own_worktree_and_branch(worktrees: Worktrees) -> None:
    worktree = worktrees.create(7, "Add the push guard")

    assert worktree.branch == "labhq/task-7-add-the-push-guard"
    assert worktree.path == worktrees.root / "task-7"
    assert run_git("branch", "--show-current", cwd=worktree.path).strip() == worktree.branch


def test_a_commit_in_the_worktree_does_not_touch_main(
    worktrees: Worktrees, repo: Path, remote: Path
) -> None:
    main_before = head(repo, "main")
    worktree = worktrees.create(7, "work")

    task_commit = commit_file(worktree.path, "feature.txt")

    assert head(repo, "main") == main_before
    assert head(remote, "main") == main_before
    assert head(repo, worktree.branch) == task_commit
    assert not (repo / "feature.txt").exists()


def test_two_tasks_get_separate_worktrees(worktrees: Worktrees) -> None:
    first = worktrees.create(1, "one")
    second = worktrees.create(2, "two")

    assert first.path != second.path
    assert first.branch != second.branch


def test_find_returns_the_task_worktree(worktrees: Worktrees) -> None:
    created = worktrees.create(12, "Find me")

    assert worktrees.find(12) == created
    assert worktrees.find(1) is None


def test_find_does_not_confuse_task_ids_with_a_common_prefix(worktrees: Worktrees) -> None:
    worktrees.create(12, "twelve")

    assert worktrees.find(1) is None
    assert worktrees.find(120) is None


def test_create_refuses_a_second_worktree_for_the_same_task(worktrees: Worktrees) -> None:
    worktrees.create(3, "first")

    with pytest.raises(WorktreeError):
        worktrees.create(3, "again")


def test_remove_keeps_the_branch_by_default(worktrees: Worktrees, repo: Path) -> None:
    worktree = worktrees.create(4, "keep")
    task_commit = commit_file(worktree.path, "kept.txt")

    worktrees.remove(4)

    assert not worktree.path.exists()
    assert worktrees.find(4) is None
    assert head(repo, worktree.branch) == task_commit


def test_remove_can_delete_the_branch(worktrees: Worktrees, repo: Path) -> None:
    worktree = worktrees.create(5, "drop")

    worktrees.remove(5, delete_branch=True)

    with pytest.raises(GitError):
        run_git("rev-parse", "--verify", worktree.branch, cwd=repo)


def test_remove_of_an_unknown_task_is_a_no_op(worktrees: Worktrees) -> None:
    worktrees.remove(99)


@pytest.mark.parametrize(
    ("title", "branch"),
    [
        ("Fix: the scheduler's reaper!", "labhq/task-9-fix-the-scheduler-s-reaper"),
        ("Café déjà vu", "labhq/task-9-cafe-deja-vu"),
        ("Διόρθωση σφάλματος", "labhq/task-9"),
        ("x" * 80, "labhq/task-9-" + "x" * 40),
    ],
)
def test_branch_names_are_ascii_slugs(title: str, branch: str) -> None:
    assert branch_name(9, title) == branch


def test_worktrees_live_under_the_data_directory(tmp_path: Path) -> None:
    assert default_root(Settings(data_dir=tmp_path)) == tmp_path / "worktrees"
