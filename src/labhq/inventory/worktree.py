"""Linked git worktrees, recognised from the `.git` file alone (no git process).

A linked worktree has a `.git` *file* reading `gitdir: <main>/.git/worktrees/<name>`. Its
sessions and its folder belong to the main checkout's project, not to a project of their own.
Submodules also have a `.git` file, but it points into `.git/modules`, so they stay projects.
"""

from pathlib import Path

GITDIR_PREFIX = "gitdir:"
WORKTREES_DIR = "worktrees"


def main_checkout(folder: Path) -> Path | None:
    """The main checkout a linked worktree at `folder` belongs to, else None."""
    entry = folder / ".git"
    try:
        if entry.is_symlink() or not entry.is_file():
            return None
        with entry.open(encoding="utf-8", errors="replace") as stream:
            first = stream.readline(4096).strip()
    except OSError:
        return None
    if not first.startswith(GITDIR_PREFIX):
        return None
    gitdir = Path(first.removeprefix(GITDIR_PREFIX).strip())
    if not gitdir.is_absolute():
        gitdir = folder / gitdir
    # <main>/.git/worktrees/<name>
    if gitdir.parent.name != WORKTREES_DIR:
        return None
    common = gitdir.parent.parent
    return common.parent.resolve() if common.name == ".git" else None
