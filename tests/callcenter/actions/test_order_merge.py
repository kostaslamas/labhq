"""A voice order can ask for a merge; only the owner's passkey can approve it (plan §5, rule 7)."""

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.approvals import MERGE_ACTION
from labhq.callcenter.actions import decide, order
from labhq.clock import FakeClock
from labhq.db.enums import ApprovalStatus, RiskClass
from labhq.db.models import Approval
from labhq.speech import speakable
from labhq.worktrees import Worktrees
from labhq.worktrees.git import run_git
from tests.db.factories import project_agent_task
from tests.worktrees.conftest import isolated_git, remote, repo
from tests.worktrees.gitrepo import commit_file

# Real git against a local bare remote, under the worktree tests' isolation.
__all__ = ["isolated_git", "remote", "repo"]


def refs(path: Path) -> str:
    return run_git("for-each-ref", "--format=%(refname) %(objectname)", "refs/heads/", cwd=path)


async def task_with_work(session: AsyncSession, clock: FakeClock, repo: Path, root: Path) -> int:
    """The id of a task whose branch holds one commit; ids survive `expire_all`."""
    project, _, task = await project_agent_task(session, clock)
    project.repo_path = str(repo)
    await session.commit()
    await session.refresh(task)
    worktree = Worktrees(repo, root).create(task.id, task.title)
    commit_file(worktree.path, "work.txt")
    return task.id


async def approvals(session: AsyncSession) -> list[Approval]:
    session.expire_all()
    return list(await session.scalars(select(Approval)))


async def test_a_merge_order_requests_approval_and_never_merges(
    session: AsyncSession, clock: FakeClock, repo: Path, remote: Path, tmp_path: Path
) -> None:
    task_id = await task_with_work(session, clock, repo, tmp_path / "worktrees")
    before = (refs(repo), refs(remote))

    answer = await order(session, clock, project="demo", text="", request_id="r1", merge=task_id)

    [approval] = await approvals(session)
    assert approval.type == MERGE_ACTION
    assert approval.risk_class == RiskClass.HEAVY
    assert approval.status == ApprovalStatus.PENDING
    assert approval.task_id == task_id
    assert answer == (
        f"Merging T{task_id} into main needs your approval, "
        f"so confirm A{approval.id} with your passkey."
    )
    assert speakable(answer) == answer
    assert (refs(repo), refs(remote)) == before


async def test_a_repeated_merge_order_asks_once(
    session: AsyncSession, clock: FakeClock, repo: Path, tmp_path: Path
) -> None:
    task_id = await task_with_work(session, clock, repo, tmp_path / "worktrees")

    first = await order(session, clock, project="demo", text="", request_id="r1", merge=task_id)
    second = await order(session, clock, project="demo", text="", request_id="r2", merge=task_id)

    assert second == first
    assert len(await approvals(session)) == 1


async def test_a_voice_decide_cannot_approve_the_merge(
    session: AsyncSession, clock: FakeClock, repo: Path, remote: Path, tmp_path: Path
) -> None:
    task_id = await task_with_work(session, clock, repo, tmp_path / "worktrees")
    await order(session, clock, project="demo", text="", request_id="r1", merge=task_id)
    [approval] = await approvals(session)
    before = (refs(repo), refs(remote))

    answer = await decide(session, clock, f"A{approval.id}", "approve")

    assert "passkey" in answer
    [still] = await approvals(session)
    assert still.status == ApprovalStatus.PENDING
    assert still.decided_by is None
    assert still.execution is None
    assert (refs(repo), refs(remote)) == before


async def test_a_merge_of_a_task_in_another_project_is_explained(
    session: AsyncSession, clock: FakeClock, repo: Path, tmp_path: Path
) -> None:
    task_id = await task_with_work(session, clock, repo, tmp_path / "worktrees")

    unknown = await order(session, clock, project="demo", text="", request_id="r1", merge=999)
    elsewhere = await order(
        session, clock, project="ghost", text="", request_id="r2", merge=task_id
    )

    assert "no task T999 in demo" in unknown
    assert "no project" in elsewhere
    assert speakable(unknown) == unknown
    assert await approvals(session) == []


async def test_a_task_without_a_branch_is_explained(
    session: AsyncSession, clock: FakeClock, repo: Path
) -> None:
    project, _, task = await project_agent_task(session, clock)
    project.repo_path = str(repo)
    task_id = task.id
    await session.commit()

    answer = await order(session, clock, project="demo", text="", request_id="r1", merge=task_id)

    assert answer.startswith("I could not request the merge.")
    assert speakable(answer) == answer
    assert await approvals(session) == []
