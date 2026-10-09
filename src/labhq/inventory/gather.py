"""What an analysis reads about one project, bounded by settings: git, code, transcript tails.

Everything is read from the project's own folder and the transcripts of its sessions. Files
git does not track are not read, which leaves out ignored secrets and build output.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from labhq.inventory.model import SavedEntry
from labhq.inventory.settings import InventorySettings
from labhq.inventory.tails import tail_of
from labhq.worktrees.git import GitError, run_git

BINARY_PROBE = 2048


@dataclass(frozen=True)
class Material:
    log: str
    status: str
    diff: str
    code: str
    tails: list[tuple[SavedEntry, str]]


def _git(root: Path, *args: str) -> str:
    try:
        return run_git(*args, cwd=root, env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
    except (GitError, OSError):
        return ""


def tracked_files(root: Path) -> list[Path]:
    raw = _git(root, "ls-files", "-z")
    return [root / name for name in raw.split("\0") if name]


def read_code(root: Path, files: list[Path], limit: int) -> str:
    """Small text files first, so as many files as fit are seen whole."""
    sized = []
    for path in files:
        try:
            if path.is_file() and not path.is_symlink():
                sized.append((path.stat().st_size, path))
        except OSError:
            continue
    parts: list[str] = []
    used = 0
    for size, path in sorted(sized):
        if used + size > limit:
            break
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if b"\0" in data[:BINARY_PROBE]:
            continue
        parts.append(f"--- {path.relative_to(root)}\n{data.decode('utf-8', errors='replace')}")
        used += size
    return "\n".join(parts)


def gather(
    root: Path, has_repo: bool, entries: list[SavedEntry], settings: InventorySettings
) -> Material:
    if has_repo:
        log = _git(
            root, "log", f"-{settings.git_log_commits}", "--date=short", "--format=%h %ad %an: %s"
        )
        status = _git(root, "status", "--short")
        diff = _git(root, "diff", "HEAD")[: settings.diff_chars]
        files = tracked_files(root)
    else:
        log = status = diff = ""
        files = [p for p in root.rglob("*") if p.is_file()][:500]
    code = read_code(root, files, settings.code_chars)
    tails = [(entry, tail_of(entry, settings.transcript_tail_chars)) for entry in entries]
    return Material(log, status, diff, code, tails)


PROMPT = """You are reviewing the work of coding agents in one project, for its owner.
Read only what is below; do not run commands or change anything.

Write a markdown report with these sections:
## What each agent did
One part per session below (tool and id), as you can see from the code, the git history
and the end of its conversation.
## What is unfinished
## What is broken
## Recommended next step per session
For each session say one of: continue, close, keep as history, and why.

Project: {name} ({root})

### Git history
{log}

### Uncommitted changes (git status)
{status}

### Uncommitted diff
{diff}

### Code
{code}

### Sessions and the end of their conversations
{sessions}
"""


def build_prompt(name: str, root: Path, material: Material) -> str:
    sessions = "\n\n".join(
        f"#### {entry.tool} {entry.session_id} "
        f"(last activity {entry.updated_at:%Y-%m-%d %H:%M} UTC)\n"
        f"{tail or '(the conversation could not be read as text)'}"
        for entry, tail in material.tails
    )
    return PROMPT.format(
        name=name,
        root=root,
        log=material.log or "(none)",
        status=material.status or "(clean)",
        diff=material.diff or "(none)",
        code=material.code or "(none)",
        sessions=sessions or "(no sessions)",
    )
