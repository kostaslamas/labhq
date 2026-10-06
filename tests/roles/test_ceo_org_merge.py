"""A CEO merge request is a heavy approval; nothing merges until the owner's passkey."""

from pathlib import Path

import pytest

from labhq.approvals import ApprovalService, ConfirmationNotAllowedError
from labhq.db.enums import ApprovalStatus, RiskClass
from labhq.db.models import Project, Task
from labhq.worktrees import Worktrees
from tests.roles.conftest import Org
from tests.worktrees.conftest import isolated_git, remote, repo
from tests.worktrees.gitrepo import commit_file, head

__all__ = ["isolated_git", "remote", "repo"]


async def task_with_branch(org: Org, repo: Path, tmp_path: Path) -> Task:
    async with org.sessions() as db:
        (await db.get_one(Project, org.site)).repo_path = str(repo)
        await db.commit()
    task = await org.get(Task, org.site_task)
    worktree = Worktrees(repo, tmp_path / "worktrees").create(task.id, task.title)
    commit_file(worktree.path, "work.txt")
    return task


async def test_a_ceo_merge_request_waits_for_a_passkey_and_merges_nothing(
    org: Org, repo: Path, remote: Path, tmp_path: Path
) -> None:
    task = await task_with_branch(org, repo, tmp_path)
    main_before = head(repo, "main")

    answer = await org.call("request_merge", org.ceo, task=task.id)

    [approval] = await org.approvals()
    assert (approval.status, approval.risk_class) == (ApprovalStatus.PENDING, RiskClass.HEAVY)
    assert approval.requested_by_agent_id == org.ceo
    assert "passkey" in answer
    assert head(repo, "main") == main_before

    service = ApprovalService(org.sessions, clock=org.clock, executors=org.executors)
    # The CEO, a tap and a voice call are all too weak for a heavy action.
    for weak in ("ceo", "tap", "voice"):
        with pytest.raises(ConfirmationNotAllowedError):
            await service.approve(approval.id, decider="agent:1", confirmation=weak)
    assert head(repo, "main") == main_before
    assert (await service.get(approval.id)).status is ApprovalStatus.PENDING

    done = await service.approve(approval.id, decider="owner", confirmation="passkey")

    assert done.status is ApprovalStatus.EXECUTED
    assert head(repo, "main") != main_before
