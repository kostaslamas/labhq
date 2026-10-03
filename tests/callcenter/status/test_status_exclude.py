from pathlib import Path

from labhq.worktrees import Worktree
from labhq.worktrees.exclude import exclude_state_dir
from labhq.worktrees.git import run_git


def test_git_add_all_in_a_task_worktree_does_not_stage_the_status_file(worktree: Worktree) -> None:
    (worktree.path / ".labhq").mkdir()
    (worktree.path / ".labhq" / "status.md").write_text("summary: x\n", encoding="utf-8")
    (worktree.path / "work.txt").write_text("work\n", encoding="utf-8")

    run_git("add", "-A", cwd=worktree.path)

    staged = run_git("diff", "--cached", "--name-only", cwd=worktree.path).split()
    assert staged == ["work.txt"]


def test_the_entry_is_written_once_and_the_tracked_gitignore_is_untouched(
    repo: Path, worktree: Worktree
) -> None:
    assert exclude_state_dir(repo) is False
    exclude = (repo / ".git" / "info" / "exclude").read_text(encoding="utf-8")
    assert exclude.splitlines().count(".labhq/") == 1
    assert not (repo / ".gitignore").exists()


def test_the_main_checkout_is_covered_by_the_same_entry(repo: Path, worktree: Worktree) -> None:
    (repo / ".labhq").mkdir()
    (repo / ".labhq" / "status.md").write_text("summary: x\n", encoding="utf-8")
    assert run_git("status", "--porcelain", cwd=repo).strip() == ""
