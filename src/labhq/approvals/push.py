"""The `push` executor: the engine publishes a task branch once its push is approved.

It runs from the project's main repository with the engine's own environment, so the
engine's git credentials apply. The worktree's disabled push URL is worktree-scoped config
and never reaches it (plan §5, rule 5). The URL is resolved here and passed explicitly, so
no `pushInsteadOf` or remote rename between request and execution changes the target.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from labhq.worktrees.git import run_git
from labhq.worktrees.manager import BRANCH_PREFIX

PUSH_ACTION = "push"


class PushPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    repo_path: str
    branch: str
    remote: str = "origin"

    @field_validator("branch")
    @classmethod
    def _task_branch_only(cls, branch: str) -> str:
        # An approved push publishes the work of one task, never main or another branch.
        if not branch.startswith(BRANCH_PREFIX):
            raise ValueError(f"only task branches ({BRANCH_PREFIX}*) can be pushed")
        return branch


def push_payload(repo: Path, branch: str, remote: str = "origin") -> dict[str, Any]:
    return PushPayload(repo_path=str(repo), branch=branch, remote=remote).model_dump()


def push_branch(payload: Mapping[str, Any]) -> dict[str, Any]:
    request = PushPayload.model_validate(payload)
    repo = Path(request.repo_path)
    url = run_git("remote", "get-url", "--push", request.remote, cwd=repo).strip()
    commit = run_git("rev-parse", "--verify", f"refs/heads/{request.branch}", cwd=repo).strip()
    ref = f"refs/heads/{request.branch}"
    # No leading `+`: an approved push never rewrites history on the remote.
    run_git("push", "--porcelain", url, f"{commit}:{ref}", cwd=repo)
    return {"url": url, "branch": request.branch, "commit": commit}
