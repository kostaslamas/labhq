"""The `push` action: publish a task branch from the main repository after approval.

The request pins everything the operator approves: the repository, the branch, the commit
and the explicit URL. The executor pushes exactly that commit to that URL from the main
repository with the engine's own environment, so a commit a worker adds after approval is
never published and the worktree's disabled push URL never applies (plan §5, rule 5).
"""

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from labhq.worktrees.git import run_git
from labhq.worktrees.manager import BRANCH_PREFIX

PUSH = "push"
# The engine has no terminal; a missing credential fails instead of waiting for input.
ENGINE_GIT_VARIABLES: Mapping[str, str] = {"GIT_TERMINAL_PROMPT": "0"}


class PushPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    repo_path: str
    branch: str
    commit: str
    url: str

    @field_validator("branch")
    @classmethod
    def _task_branch(cls, branch: str) -> str:
        # Only task branches are published this way; main changes through `merge`.
        if not branch.startswith(BRANCH_PREFIX):
            raise ValueError(f"only task branches ({BRANCH_PREFIX}*) can be pushed")
        return branch

    @property
    def refspec(self) -> str:
        return f"{self.commit}:refs/heads/{self.branch}"


def push_payload(repo: Path, branch: str, *, remote: str = "origin") -> dict[str, Any]:
    """Resolve what a push of `branch` would publish, for the operator to approve."""
    commit = run_git("rev-parse", "--verify", f"refs/heads/{branch}^{{commit}}", cwd=repo)
    url = run_git("remote", "get-url", "--push", remote, cwd=repo)
    payload = PushPayload(
        repo_path=str(repo), branch=branch, commit=commit.strip(), url=url.strip()
    )
    return payload.model_dump()


def engine_environment() -> dict[str, str]:
    """The engine's own environment, credentials included, unlike `worker_environment`."""
    return {**os.environ, **ENGINE_GIT_VARIABLES}


def execute_push(payload: Mapping[str, Any]) -> dict[str, Any]:
    push = PushPayload.model_validate(dict(payload))
    repo = Path(push.repo_path)
    run_git("push", "--quiet", push.url, push.refspec, cwd=repo, env=engine_environment())
    return {"url": push.url, "ref": f"refs/heads/{push.branch}", "commit": push.commit}
