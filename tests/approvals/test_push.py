"""A push is requested by an agent, approved by a human and executed by the engine."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from labhq.approvals import PUSH_ACTION, ApprovalNotPendingError, push_payload
from labhq.db.enums import ApprovalStatus, RiskClass
from labhq.worktrees import Worktree
from labhq.worktrees.git import run_git
from tests.approvals.conftest import World
from tests.worktrees.gitrepo import commit_file, head


def remote_refs(remote: Path) -> str:
    return run_git("for-each-ref", "--format=%(refname) %(objectname)", cwd=remote)


async def request_push(world: World, repo: Path, worktree: Worktree) -> int:
    approval = await world.service.request(
        PUSH_ACTION,
        push_payload(repo, worktree.branch),
        task_id=world.task_id,
        agent_id=world.agent_id,
    )
    return approval.id


async def test_a_push_request_is_pending_and_pushes_nothing(
    world: World, repo: Path, remote: Path, worktree: Worktree
) -> None:
    before = remote_refs(remote)

    approval_id = await request_push(world, repo, worktree)

    approval = await world.service.get(approval_id)
    assert approval.status == ApprovalStatus.PENDING
    assert approval.risk_class == RiskClass.HEAVY
    assert approval.executed_at is None
    assert approval.execution is None
    assert remote_refs(remote) == before
    assert [a.id for a in await world.service.list(ApprovalStatus.PENDING)] == [approval_id]


async def test_after_approval_the_engine_pushes_the_branch(
    world: World, repo: Path, remote: Path, worktree: Worktree
) -> None:
    approval_id = await request_push(world, repo, worktree)
    world.clock.advance(60)

    approval = await world.service.approve(approval_id, decider="operator", confirmation="cli")

    assert head(remote, worktree.branch) == head(worktree.path)
    assert approval.status == ApprovalStatus.EXECUTED
    assert approval.executed_at == world.clock.now()
    assert approval.execution == {
        "url": str(remote),
        "branch": worktree.branch,
        "commit": head(worktree.path),
    }
    assert (await world.service.get(approval_id)).status == ApprovalStatus.EXECUTED


async def test_a_rejected_push_never_executes(
    world: World, repo: Path, remote: Path, worktree: Worktree
) -> None:
    before = remote_refs(remote)
    approval_id = await request_push(world, repo, worktree)

    rejected = await world.service.reject(approval_id, decider="operator", confirmation="cli")
    with pytest.raises(ApprovalNotPendingError):
        await world.service.approve(approval_id, decider="operator", confirmation="cli")

    assert rejected.status == ApprovalStatus.REJECTED
    stored = await world.service.get(approval_id)
    assert stored.status == ApprovalStatus.REJECTED
    assert stored.executed_at is None
    assert stored.execution is None
    assert remote_refs(remote) == before


async def test_an_approval_executes_at_most_once(
    world: World, repo: Path, remote: Path, worktree: Worktree
) -> None:
    approval_id = await request_push(world, repo, worktree)
    await world.service.approve(approval_id, decider="operator", confirmation="cli")
    pushed = head(remote, worktree.branch)
    commit_file(worktree.path, "later.txt")

    with pytest.raises(ApprovalNotPendingError):
        await world.service.approve(approval_id, decider="operator", confirmation="cli")

    assert head(remote, worktree.branch) == pushed


async def test_the_push_uses_the_main_repository_not_the_worktree_config(
    world: World, repo: Path, remote: Path, worktree: Worktree
) -> None:
    # The worktree's push URL is disabled; the engine resolves the URL in the main checkout.
    worktree_push_url = run_git("remote", "get-url", "--push", "origin", cwd=worktree.path)
    assert worktree_push_url.strip() != str(remote)

    approval = await world.service.approve(
        await request_push(world, repo, worktree), decider="operator", confirmation="cli"
    )

    assert approval.execution is not None
    assert approval.execution["url"] == str(remote)


async def test_a_failed_push_is_recorded_as_execution_failed(
    world: World, repo: Path, remote: Path, worktree: Worktree
) -> None:
    approval_id = await request_push(world, repo, worktree)
    run_git("remote", "set-url", "origin", str(remote.parent / "missing.git"), cwd=repo)

    approval = await world.service.approve(approval_id, decider="operator", confirmation="cli")

    assert approval.status == ApprovalStatus.EXECUTION_FAILED
    assert approval.executed_at == world.clock.now()
    assert approval.execution is not None
    assert approval.execution["error"] == "GitError"
    assert worktree.branch not in remote_refs(remote)


@pytest.mark.parametrize("branch", ["main", "feature/x", "refs/heads/labhq/task-1"])
async def test_only_task_branches_can_be_requested(world: World, repo: Path, branch: str) -> None:
    with pytest.raises(ValidationError):
        await world.service.request(
            PUSH_ACTION, {"repo_path": str(repo), "branch": branch}, task_id=world.task_id
        )

    assert await world.service.list() == []
