"""Task worktrees and the credential-free environment workers run in."""

from labhq.worktrees.environment import worker_environment
from labhq.worktrees.git import GitError

__all__ = ["GitError", "worker_environment"]
