"""The owner's main checkout, read without writing: changed paths and a fingerprint.

`GIT_OPTIONAL_LOCKS=0` keeps `git status` from refreshing the index, so reading the
checkout never writes to it. The fingerprint covers HEAD, the status and each changed
path's size and modification time, so a second edit to an already modified file shows.
"""

import hashlib
import os
from pathlib import Path

from labhq.worktrees.git import GitError, run_git

READ_ONLY_GIT = {"GIT_OPTIONAL_LOCKS": "0"}


def _git(*args: str, repo: Path) -> str:
    return run_git(*args, cwd=repo, env={**os.environ, **READ_ONLY_GIT})


def toplevel(path: Path) -> Path:
    try:
        return Path(_git("rev-parse", "--show-toplevel", repo=path).strip())
    except GitError as error:
        if "not a git repository" not in error.stderr:
            raise
        return path.resolve()


def is_git_repository(path: Path) -> bool:
    try:
        _git("rev-parse", "--show-toplevel", repo=path)
    except GitError as error:
        if "not a git repository" not in error.stderr:
            raise
        return False
    return True


def changed_paths(repo: Path) -> list[str]:
    """Paths with uncommitted changes, untracked files included, `.labhq/` excluded."""
    if not is_git_repository(repo):
        return []
    raw = _git("status", "--porcelain=v1", "-z", "--untracked-files=all", repo=repo)
    fields = raw.split("\0")
    paths: list[str] = []
    index = 0
    while index < len(fields):
        entry = fields[index]
        index += 1
        if len(entry) < 4:
            continue
        paths.append(entry[3:])
        # A rename or copy carries its source path as the next field.
        if entry[0] in "RC":
            index += 1
    return paths


def fingerprint(repo: Path) -> str:
    if not is_git_repository(repo):
        parts: list[str] = []
        for root, dirs, files in os.walk(repo):
            dirs[:] = sorted(name for name in dirs if name != ".labhq")
            for name in sorted(files):
                target = Path(root) / name
                stat = target.lstat()
                parts.append(f"{target.relative_to(repo)} {stat.st_size} {stat.st_mtime_ns}")
        return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
    head = _git("rev-parse", "--verify", "--quiet", "HEAD", repo=repo).strip()
    parts = [head]
    for path in changed_paths(repo):
        target = repo / path
        try:
            stat = target.stat()
            parts.append(f"{path} {stat.st_size} {stat.st_mtime_ns}")
        except FileNotFoundError:
            parts.append(f"{path} missing")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
