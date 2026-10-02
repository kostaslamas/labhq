"""Task worktrees and the credential-free environment workers run in."""

from labhq.worktrees.environment import worker_environment
from labhq.worktrees.git import GitError
from labhq.worktrees.manager import (
    PUSH_DISABLED_URL,
    Worktree,
    WorktreeError,
    Worktrees,
    branch_name,
    default_root,
)

__all__ = [
    "PUSH_DISABLED_URL",
    "GitError",
    "Worktree",
    "WorktreeError",
    "Worktrees",
    "branch_name",
    "default_root",
    "worker_environment",
]
