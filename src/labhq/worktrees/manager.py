"""One git worktree and branch per task, under the data directory.

A worker commits in its worktree and can never push from it: worktree-scoped config points
every remote's push URL at a path that cannot exist, and an empty `pushInsteadOf` prefix
rewrites any other URL to the same place. The engine publishes later from the main
repository, which carries none of this config (plan §5, rule 5).
"""

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from labhq.settings import Settings
from labhq.worktrees.git import run_git

BRANCH_PREFIX = "labhq/task-"
# A path below a character device: no process can create it, so no push can reach it.
PUSH_DISABLED_URL = "/dev/null/labhq-push-disabled"
SLUG_MAX_LENGTH = 40


class WorktreeError(RuntimeError):
    pass


@dataclass(frozen=True)
class Worktree:
    task_id: int
    path: Path
    branch: str


def default_root(settings: Settings) -> Path:
    return settings.data_dir / "worktrees"


def task_slug(title: str) -> str:
    """An ASCII slug of `title`; empty when nothing ASCII survives (a Greek title, say)."""
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_title.lower()).strip("-")
    return slug[:SLUG_MAX_LENGTH].rstrip("-")


def branch_name(task_id: int, title: str) -> str:
    slug = task_slug(title)
    return f"{BRANCH_PREFIX}{task_id}-{slug}" if slug else f"{BRANCH_PREFIX}{task_id}"


class Worktrees:
    """Create, find and remove task worktrees of one repository."""

    def __init__(self, repo: Path, root: Path) -> None:
        self.repo = repo
        self.root = root

    def path_for(self, task_id: int) -> Path:
        return self.root / f"task-{task_id}"

    def create(self, task_id: int, title: str, *, base: str = "HEAD") -> Worktree:
        if self.find(task_id) is not None:
            raise WorktreeError(f"task {task_id} already has a worktree")
        worktree = Worktree(task_id, self.path_for(task_id), branch_name(task_id, title))
        self.root.mkdir(parents=True, exist_ok=True)
        run_git("worktree", "add", "-b", worktree.branch, str(worktree.path), base, cwd=self.repo)
        self._disable_push(worktree.path)
        return worktree

    def find(self, task_id: int) -> Worktree | None:
        listing = run_git("worktree", "list", "--porcelain", cwd=self.repo)
        for path, branch in _porcelain_entries(listing):
            if _task_id_of(branch) == task_id:
                return Worktree(task_id, path, branch)
        return None

    def remove(self, task_id: int, *, delete_branch: bool = False) -> None:
        """Remove the worktree. The branch stays by default: it holds the work to publish."""
        worktree = self.find(task_id)
        if worktree is None:
            return
        run_git("worktree", "remove", "--force", str(worktree.path), cwd=self.repo)
        if delete_branch:
            run_git("branch", "-D", worktree.branch, cwd=self.repo)

    def _disable_push(self, path: Path) -> None:
        run_git("config", "extensions.worktreeConfig", "true", cwd=self.repo)
        for remote in run_git("remote", cwd=path).split():
            run_git("config", "--worktree", f"remote.{remote}.pushurl", PUSH_DISABLED_URL, cwd=path)
        # An empty prefix matches every URL, so a remote added later or a URL typed on the
        # command line is rewritten too. Remotes with a push URL ignore it, hence the loop.
        run_git("config", "--worktree", f"url.{PUSH_DISABLED_URL}.pushInsteadOf", "", cwd=path)


def _porcelain_entries(listing: str) -> list[tuple[Path, str]]:
    entries: list[tuple[Path, str]] = []
    for block in listing.strip().split("\n\n"):
        fields = dict(line.partition(" ")[::2] for line in block.splitlines())
        if "worktree" in fields and "branch" in fields:
            branch = fields["branch"].removeprefix("refs/heads/")
            entries.append((Path(fields["worktree"]), branch))
    return entries


def _task_id_of(branch: str) -> int | None:
    match = re.fullmatch(re.escape(BRANCH_PREFIX) + r"(\d+)(?:-.*)?", branch)
    return int(match.group(1)) if match else None
