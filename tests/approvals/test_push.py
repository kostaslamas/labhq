"""A push is requested by an agent and carried out by the engine only after approval."""

from pathlib import Path

import pytest

from labhq.approvals import PUSH, ApprovalService, Decision, push_payload
from labhq.db.enums import ApprovalStatus, RiskClass
from labhq.worktrees import Worktree
from labhq.worktrees.git import run_git
from tests.worktrees.gitrepo import commit_file, head

OPERATOR = Decision(decided_by="operator", confirmation_kind="cli")


def remote_refs(remote: Path) -> str:
    return run_git("for-each-ref", "--format=%(refname) %(objectname)", cwd=remote)


def remote_head(remote: Path, branch: str) -> str:
    return head(remote, f"refs/heads/{branch}")


async def test_a_push_request_is_pending_and_pushes_nothing(
    service: ApprovalService, repo: Path, remote: Path, worktree: Worktree
) -> None:
    before = remote_refs(remote)

    approval = await service.request(PUSH, push_payload(repo, worktree.branch))

    assert approval.status is ApprovalStatus.PENDING
    assert approval.risk_class is RiskClass.HEAVY
    assert approval.payload["url"] == str(remote)
    assert approval.payload["commit"] == head(worktree.path)
    assert [a.id for a in await service.list(status=ApprovalStatus.PENDING)] == [approval.id]
    assert remote_refs(remote) == before


async def test_after_approval_the_engine_pushes_and_records_the_execution(
    service: ApprovalService, repo: Path, remote: Path, worktree: Worktree
) -> None:
    approval = await service.request(PUSH, push_payload(repo, worktree.branch))

    executed = await service.approve(approval.id, OPERATOR)

    assert executed.status is ApprovalStatus.EXECUTED
    assert remote_head(remote, worktree.branch) == head(worktree.path)
    assert executed.executed_at is not None
    assert executed.execution == {
        "url": str(remote),
        "ref": f"refs/heads/{worktree.branch}",
        "commit": head(worktree.path),
    }


async def test_the_push_publishes_the_approved_commit_not_later_work(
    service: ApprovalService, repo: Path, remote: Path, worktree: Worktree
) -> None:
    approved_commit = head(worktree.path)
    approval = await service.request(PUSH, push_payload(repo, worktree.branch))
    commit_file(worktree.path, "after-request.txt")

    await service.approve(approval.id, OPERATOR)

    assert remote_head(remote, worktree.branch) == approved_commit


async def test_the_push_runs_from_the_main_repository_not_the_worktree(
    service: ApprovalService, repo: Path, remote: Path, worktree: Worktree
) -> None:
    # The worktree's own push URL is disabled; a push from there would fail.
    approval = await service.request(PUSH, push_payload(repo, worktree.branch))

    executed = await service.approve(approval.id, OPERATOR)

    assert executed.status is ApprovalStatus.EXECUTED
    assert approval.payload["repo_path"] == str(repo)


async def test_a_failed_push_is_recorded_as_execution_failed(
    service: ApprovalService, repo: Path, remote: Path, worktree: Worktree, tmp_path: Path
) -> None:
    payload = push_payload(repo, worktree.branch) | {"url": str(tmp_path / "missing.git")}
    approval = await service.request(PUSH, payload)

    failed = await service.approve(approval.id, OPERATOR)

    assert failed.status is ApprovalStatus.EXECUTION_FAILED
    assert failed.execution is not None
    assert "GitError" in failed.execution["error"]
    assert failed.executed_at is not None


def test_only_task_branches_can_be_requested(repo: Path) -> None:
    with pytest.raises(ValueError, match="task branches"):
        push_payload(repo, "main")
