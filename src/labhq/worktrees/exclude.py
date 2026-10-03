"""Keep `.labhq/` out of commits (ADR 0004).

The entry goes into `info/exclude` of the repository's common git directory, which every
worktree shares, so one write covers the main checkout and all task worktrees. The tracked
`.gitignore` is never touched. Exclusion stops an accidental `git add -A`; `git add -f`
still gets through.
"""

from pathlib import Path

from labhq.worktrees.git import run_git

STATE_DIR = ".labhq"
EXCLUDE_ENTRY = f"{STATE_DIR}/"


def exclude_state_dir(repo: Path) -> bool:
    """Ensure `.labhq/` is excluded in `repo`'s git directory; return whether it was added."""
    common = Path(run_git("rev-parse", "--git-common-dir", cwd=repo).strip())
    exclude = (repo / common if not common.is_absolute() else common) / "info" / "exclude"
    existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    if EXCLUDE_ENTRY in (line.strip() for line in existing.splitlines()):
        return False
    exclude.parent.mkdir(parents=True, exist_ok=True)
    separator = "" if not existing or existing.endswith("\n") else "\n"
    exclude.write_text(f"{existing}{separator}{EXCLUDE_ENTRY}\n", encoding="utf-8")
    return True
