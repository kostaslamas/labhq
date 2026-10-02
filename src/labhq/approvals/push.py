"""The `push` executor: the engine publishes a task branch once its push is approved.

The request pins what the operator approves: the commit and the explicit push URL are
resolved in the project's main repository when the approval is requested, and execution
pushes exactly that commit to that URL or fails. A commit a worker adds after the request,
or a remote changed meanwhile, never alters what is published.

It runs from the main repository with the engine's own environment, so the engine's git
credentials apply. The worktree's disabled push URL is worktree-scoped config and never
reaches it (plan §5, rule 5).
"""

import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from labhq.worktrees.git import run_git
from labhq.worktrees.manager import BRANCH_PREFIX

PUSH_ACTION = "push"
# SHA-1 or SHA-256 object names, in full: an abbreviation could resolve differently later.
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
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
    def _task_branch_only(cls, branch: str) -> str:
        # An approved push publishes the work of one task, never main or another branch.
        if not branch.startswith(BRANCH_PREFIX):
            raise ValueError(f"only task branches ({BRANCH_PREFIX}*) can be pushed")
        return branch

    @field_validator("commit")
    @classmethod
    def _full_object_name(cls, commit: str) -> str:
        if not COMMIT_PATTERN.fullmatch(commit):
            raise ValueError("commit must be a full object name")
        return commit

    @field_validator("url")
    @classmethod
    def _non_empty_url(cls, url: str) -> str:
        if not url.strip():
            raise ValueError("url must not be empty")
        return url


def push_payload(repo: Path, branch: str, remote: str = "origin") -> dict[str, Any]:
    """Pin what a push of `branch` would publish now, for the operator to approve."""
    commit = run_git("rev-parse", "--verify", f"refs/heads/{branch}^{{commit}}", cwd=repo)
    url = run_git("remote", "get-url", "--push", remote, cwd=repo)
    payload = PushPayload(
        repo_path=str(repo), branch=branch, commit=commit.strip(), url=url.strip()
    )
    return payload.model_dump()


def engine_environment() -> dict[str, str]:
    """The engine's own environment, credentials included, unlike `worker_environment`."""
    return {**os.environ, **ENGINE_GIT_VARIABLES}


def push_branch(payload: Mapping[str, Any]) -> dict[str, Any]:
    request = PushPayload.model_validate(payload)
    ref = f"refs/heads/{request.branch}"
    # No leading `+`: an approved push never rewrites history on the remote.
    run_git(
        "push",
        "--porcelain",
        request.url,
        f"{request.commit}:{ref}",
        cwd=Path(request.repo_path),
        env=engine_environment(),
    )
    return {"url": request.url, "branch": request.branch, "commit": request.commit}
