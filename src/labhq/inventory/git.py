"""Cheap git facts about a project, read without writing to it.

Every command is read-only (`GIT_OPTIONAL_LOCKS=0`). The open pull request comes from
`gh`, only when it is installed and logged in; a missing or logged-out `gh` is not an error.
"""

import json
import os
import shutil
import subprocess
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from labhq.adoption.checkout import changed_paths, is_git_repository, toplevel
from labhq.inventory.model import GitFacts
from labhq.inventory.worktree import main_checkout
from labhq.worktrees.git import GitError, run_git

# Runs a command in a folder; returns stdout, or None when it cannot run or fails.
Command = Callable[[Sequence[str], Path, float], str | None]


def run_command(argv: Sequence[str], cwd: Path, timeout: float) -> str | None:
    if shutil.which(argv[0]) is None:
        return None
    try:
        result = subprocess.run(
            list(argv), cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def git_root(folder: Path) -> Path | None:
    """The git root of `folder`, or None for a folder without a repository.

    A linked worktree answers with its main checkout, so its sessions join that project.
    """
    if not folder.is_dir() or not is_git_repository(folder):
        return None
    top = toplevel(folder).resolve()
    return main_checkout(top) or top


def _git(root: Path, *args: str) -> str | None:
    try:
        return run_git(*args, cwd=root, env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"}).strip()
    except (GitError, OSError):
        return None


def git_facts(
    root: Path, *, use_gh: bool, timeout: float, command: Command = run_command
) -> GitFacts:
    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    last = _git(root, "log", "-1", "--format=%ct%x00%s")
    when: datetime | None = None
    subject: str | None = None
    if last and "\0" in last:
        stamp, _, subject = last.partition("\0")
        when = datetime.fromtimestamp(int(stamp), tz=UTC)
    pr = open_pull_request(root, branch, timeout=timeout, command=command) if use_gh else None
    return GitFacts(
        branch=branch,
        dirty_files=len(changed_paths(root)),
        last_commit_subject=subject,
        last_commit_at=when,
        open_pr=pr,
    )


def open_pull_request(
    root: Path, branch: str | None, *, timeout: float, command: Command = run_command
) -> str | None:
    if branch is None or branch == "HEAD":
        return None
    # `gh auth status` exits non-zero when logged out; it prints no token.
    if command(("gh", "auth", "status"), root, timeout) is None:
        return None
    raw = command(("gh", "pr", "view", branch, "--json", "number,title,state,url"), root, timeout)
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("state") != "OPEN":
        return None
    return f"#{data.get('number')} {data.get('title', '')}".strip()
