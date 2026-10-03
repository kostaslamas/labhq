"""The `merge` executor: the engine merges a task branch into its target once approved.

The request pins what the owner approves: the task branch and its commit, the target branch
and the target's commit, and the explicit push URL, all resolved in the project's main
repository at request time. Execution re-checks both refs, merges exactly the pinned commit
with `--no-ff` in a temporary worktree detached at the pinned target, and pushes the result
to the pinned URL without force. Anything that moved, and any conflict, fails the approval
before a ref changes (plan §5, rules 5 and 8).

The local target follows the published one afterwards, and only as a fast-forward: a target
checked out in a worktree is fast-forwarded there by git, which never discards local edits;
otherwise its ref is updated against the pinned old value.
"""

import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from labhq.approvals.push import COMMIT_PATTERN, engine_environment
from labhq.worktrees.git import GitError, run_git
from labhq.worktrees.manager import BRANCH_PREFIX

MERGE_ACTION = "merge"
DEFAULT_TARGET = "main"


class MergeError(RuntimeError):
    """An approved merge the engine refused to carry out; nothing was changed."""


class MergePayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    repo_path: str
    branch: str
    commit: str
    target: str
    target_commit: str
    url: str

    @field_validator("branch")
    @classmethod
    def _task_branch_only(cls, branch: str) -> str:
        if not branch.startswith(BRANCH_PREFIX):
            raise ValueError(f"only task branches ({BRANCH_PREFIX}*) can be merged")
        return branch

    @field_validator("target")
    @classmethod
    def _plain_branch_name(cls, target: str) -> str:
        # A short name only: `refs/...` or an option-like name would change what git reads.
        if not target or target.startswith(("-", "refs/")) or target.startswith(BRANCH_PREFIX):
            raise ValueError("target must be a plain branch name that is not a task branch")
        return target

    @field_validator("commit", "target_commit")
    @classmethod
    def _full_object_name(cls, commit: str) -> str:
        if not COMMIT_PATTERN.fullmatch(commit):
            raise ValueError("commits must be full object names")
        return commit

    @field_validator("url")
    @classmethod
    def _non_empty_url(cls, url: str) -> str:
        if not url.strip():
            raise ValueError("url must not be empty")
        return url

    @model_validator(mode="after")
    def _distinct_commits(self) -> Self:
        if self.commit == self.target_commit:
            raise ValueError("the branch has nothing to merge into the target")
        return self


def _ref_commit(repo: Path, branch: str) -> str:
    return run_git("rev-parse", "--verify", f"refs/heads/{branch}^{{commit}}", cwd=repo).strip()


def _is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    try:
        run_git("merge-base", "--is-ancestor", ancestor, descendant, cwd=repo)
    except GitError as error:
        if error.returncode == 1:
            return False
        raise
    return True


def merge_payload(
    repo: Path, branch: str, target: str = DEFAULT_TARGET, remote: str = "origin"
) -> dict[str, Any]:
    """Pin what merging `branch` into `target` would publish now, for the owner to approve."""
    commit = _ref_commit(repo, branch)
    target_commit = _ref_commit(repo, target)
    if _is_ancestor(repo, commit, target_commit):
        raise MergeError(f"{branch} is already merged into {target}")
    url = run_git("remote", "get-url", "--push", remote, cwd=repo).strip()
    payload = MergePayload(
        repo_path=str(repo),
        branch=branch,
        commit=commit,
        target=target,
        target_commit=target_commit,
        url=url,
    )
    return payload.model_dump()


def _check_unmoved(repo: Path, branch: str, pinned: str) -> None:
    try:
        current = _ref_commit(repo, branch)
    except GitError:
        raise MergeError(f"{branch} no longer exists") from None
    if current != pinned:
        raise MergeError(f"{branch} moved since the request: {pinned} is now {current}")


def _merge_commit(request: MergePayload, repo: Path, scratch: Path) -> str:
    """Merge the pinned commit onto the pinned target in a throwaway worktree."""
    run_git("worktree", "add", "--quiet", "--detach", str(scratch), request.target_commit, cwd=repo)
    try:
        run_git(
            "merge",
            "--no-ff",
            "--no-edit",
            "-m",
            f"Merge {request.branch} into {request.target}",
            request.commit,
            cwd=scratch,
            env=engine_environment(),
        )
        return run_git("rev-parse", "HEAD", cwd=scratch).strip()
    except GitError as error:
        raise MergeError(
            f"merging {request.branch} into {request.target} failed: {error.stderr.strip()}"
        ) from None
    finally:
        run_git("worktree", "remove", "--force", str(scratch), cwd=repo)


def _checkout_of(repo: Path, branch: str) -> Path | None:
    listing = run_git("worktree", "list", "--porcelain", cwd=repo)
    for block in listing.strip().split("\n\n"):
        fields = dict(line.partition(" ")[::2] for line in block.splitlines())
        if fields.get("branch") == f"refs/heads/{branch}":
            return Path(fields["worktree"])
    return None


def _advance_local(request: MergePayload, repo: Path, merged: str) -> bool:
    """Fast-forward the local target to the published merge; never force it."""
    checkout = _checkout_of(repo, request.target)
    try:
        if checkout is None:
            ref = f"refs/heads/{request.target}"
            run_git("update-ref", ref, merged, request.target_commit, cwd=repo)
        else:
            run_git("merge", "--ff-only", "--quiet", merged, cwd=checkout)
    except GitError:
        # Published already; a local edit in the way is the owner's to resolve with a pull.
        return False
    return True


def merge_branch(payload: Mapping[str, Any]) -> dict[str, Any]:
    request = MergePayload.model_validate(payload)
    repo = Path(request.repo_path)
    _check_unmoved(repo, request.branch, request.commit)
    _check_unmoved(repo, request.target, request.target_commit)
    with tempfile.TemporaryDirectory(prefix="labhq-merge-") as scratch:
        merged = _merge_commit(request, repo, Path(scratch) / "merge")
    ref = f"refs/heads/{request.target}"
    try:
        # No leading `+`: a remote target that moved rejects the push as non-fast-forward.
        run_git(
            "push",
            "--porcelain",
            request.url,
            f"{merged}:{ref}",
            cwd=repo,
            env=engine_environment(),
        )
    except GitError as error:
        raise MergeError(
            f"pushing {request.target} to {request.url} failed: {error.stderr.strip()}"
        ) from None
    return {
        "url": request.url,
        "branch": request.branch,
        "commit": request.commit,
        "target": request.target,
        "merge_commit": merged,
        "local_target_updated": _advance_local(request, repo, merged),
    }
