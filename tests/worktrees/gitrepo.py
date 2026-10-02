"""Small git helpers shared by the worktree tests."""

from pathlib import Path

from labhq.worktrees.git import run_git


def head(path: Path, ref: str = "HEAD") -> str:
    return run_git("rev-parse", ref, cwd=path).strip()


def commit_file(path: Path, name: str) -> str:
    (path / name).write_text(f"{name}\n", encoding="utf-8")
    run_git("add", name, cwd=path)
    run_git("commit", "--quiet", "-m", f"add {name}", cwd=path)
    return head(path)
