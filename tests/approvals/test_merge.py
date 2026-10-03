"""A merge is requested, approved by a human and executed by the engine, or refused unchanged."""

import ast
import inspect
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from labhq.approvals import MERGE_ACTION, MergeError, default_executors, merge_payload
from labhq.approvals import service as service_module
from labhq.approvals.merge import merge_branch
from labhq.db.enums import ApprovalStatus, RiskClass
from labhq.db.models import Notification, Project, Task
from labhq.work import WorkError, request_merge
from labhq.worktrees import Worktree, Worktrees
from labhq.worktrees.git import run_git
from tests.approvals.conftest import World
from tests.worktrees.gitrepo import commit_file, head


def refs(path: Path) -> str:
    return run_git("for-each-ref", "--format=%(refname) %(objectname)", "refs/heads/", cwd=path)


def write_commit(path: Path, name: str, content: str) -> str:
    (path / name).write_text(content, encoding="utf-8")
    run_git("add", name, cwd=path)
    run_git("commit", "--quiet", "-m", f"write {name}", cwd=path)
    return head(path)


async def request(world: World, repo: Path, worktree: Worktree) -> int:
    approval = await world.service.request(
        MERGE_ACTION, merge_payload(repo, worktree.branch), task_id=world.task_id
    )
    return approval.id


async def approve(world: World, approval_id: int) -> tuple[ApprovalStatus, dict[str, object]]:
    approval = await world.service.approve(approval_id, decider="operator", confirmation="cli")
    assert approval.execution is not None
    return approval.status, approval.execution


async def test_a_merge_request_is_pending_and_changes_no_branch(
    world: World, repo: Path, remote: Path, worktree: Worktree
) -> None:
    before = (refs(repo), refs(remote))

    approval = await world.service.get(await request(world, repo, worktree))

    assert approval.status == ApprovalStatus.PENDING
    assert approval.risk_class == RiskClass.HEAVY
    assert approval.execution is None
    assert approval.payload["commit"] == head(worktree.path)
    assert approval.payload["target"] == "main"
    assert approval.payload["target_commit"] == head(repo, "main")
    assert approval.payload["url"] == str(remote)
    assert (refs(repo), refs(remote)) == before


async def test_after_approval_the_engine_merges_the_pinned_commit_and_pushes_main(
    world: World, repo: Path, remote: Path, worktree: Worktree
) -> None:
    target_before = head(repo, "main")
    approval_id = await request(world, repo, worktree)
    pinned = head(worktree.path)

    status, execution = await approve(world, approval_id)

    merged = head(remote, "main")
    assert status == ApprovalStatus.EXECUTED
    assert execution["merge_commit"] == merged
    assert execution["local_target_updated"] is True
    parents = run_git("rev-list", "--parents", "-n", "1", merged, cwd=remote).split()
    assert parents == [merged, target_before, pinned]  # --no-ff: always a merge commit
    assert head(repo, "main") == merged
    assert (repo / "work.txt").is_file()  # the checked-out main was fast-forwarded
    assert run_git("status", "--porcelain", cwd=repo) == ""
    assert head(repo, worktree.branch) == pinned
    assert "labhq-merge-" not in run_git("worktree", "list", cwd=repo)


async def test_a_target_not_checked_out_is_updated_by_ref(
    world: World, repo: Path, remote: Path, worktree: Worktree
) -> None:
    run_git("checkout", "--quiet", "--detach", cwd=repo)
    approval_id = await request(world, repo, worktree)

    status, execution = await approve(world, approval_id)

    assert status == ApprovalStatus.EXECUTED
    assert head(repo, "main") == head(remote, "main") == execution["merge_commit"]


async def test_a_branch_that_moved_after_the_request_fails_unchanged(
    world: World, repo: Path, remote: Path, worktree: Worktree
) -> None:
    approval_id = await request(world, repo, worktree)
    commit_file(worktree.path, "after-request.txt")
    before = (refs(repo), refs(remote))

    status, execution = await approve(world, approval_id)

    assert status == ApprovalStatus.EXECUTION_FAILED
    assert execution["error"] == "MergeError"
    assert f"{worktree.branch} moved since the request" in str(execution["message"])
    assert (refs(repo), refs(remote)) == before


async def test_a_target_that_moved_after_the_request_fails_unchanged(
    world: World, repo: Path, remote: Path, worktree: Worktree
) -> None:
    approval_id = await request(world, repo, worktree)
    commit_file(repo, "meanwhile.txt")
    before = (refs(repo), refs(remote))

    status, execution = await approve(world, approval_id)

    assert status == ApprovalStatus.EXECUTION_FAILED
    assert "main moved since the request" in str(execution["message"])
    assert (refs(repo), refs(remote)) == before


async def test_a_remote_target_that_moved_rejects_the_push_unchanged(
    world: World, repo: Path, remote: Path, worktree: Worktree, tmp_path: Path
) -> None:
    approval_id = await request(world, repo, worktree)
    other = tmp_path / "other"
    run_git("clone", "--quiet", str(remote), str(other), cwd=tmp_path)
    commit_file(other, "elsewhere.txt")
    run_git("push", "--quiet", "origin", "main", cwd=other)
    before = (refs(repo), refs(remote))

    status, execution = await approve(world, approval_id)

    assert status == ApprovalStatus.EXECUTION_FAILED
    assert "pushing main" in str(execution["message"])
    assert (refs(repo), refs(remote)) == before


async def test_a_conflicting_merge_fails_unchanged(
    world: World, repo: Path, remote: Path, tmp_path: Path
) -> None:
    worktree = Worktrees(repo, tmp_path / "worktrees").create(7, "conflict")
    write_commit(worktree.path, "README.md", "the task's words\n")
    write_commit(repo, "README.md", "the owner's words\n")
    approval_id = await request(world, repo, worktree)
    before = (refs(repo), refs(remote))

    status, execution = await approve(world, approval_id)

    assert status == ApprovalStatus.EXECUTION_FAILED
    assert "merging" in str(execution["message"])
    assert (refs(repo), refs(remote)) == before
    assert run_git("status", "--porcelain", cwd=repo) == ""


def test_an_already_merged_branch_cannot_be_requested(repo: Path, tmp_path: Path) -> None:
    worktree = Worktrees(repo, tmp_path / "worktrees").create(7, "empty")

    with pytest.raises(MergeError, match="already merged"):
        merge_payload(repo, worktree.branch)


@pytest.mark.parametrize(
    "change",
    [
        {"branch": "main"},
        {"target": "refs/heads/main"},
        {"target": "--force"},
        {"target": "labhq/task-9"},
        {"commit": "abc123"},
        {"target_commit": "HEAD"},
        {"url": " "},
    ],
)
async def test_a_malformed_merge_is_refused_at_request_time(
    world: World, repo: Path, worktree: Worktree, change: dict[str, str]
) -> None:
    payload = merge_payload(repo, worktree.branch) | change

    with pytest.raises(ValidationError):
        await world.service.request(MERGE_ACTION, payload, task_id=world.task_id)

    assert await world.service.list() == []


def test_the_executor_is_one_registration() -> None:
    assert default_executors.get(MERGE_ACTION).run is merge_branch


def test_the_approvals_service_never_branches_on_an_action_name() -> None:
    tree = ast.parse(inspect.getsource(service_module))
    literals = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant)}

    assert not literals & {MERGE_ACTION, "push", *default_executors}


async def point_project_at(world: World, repo: Path) -> Task:
    async with world.sessions() as db:
        task = await db.get_one(Task, world.task_id)
        (await db.get_one(Project, task.project_id)).repo_path = str(repo)
        await db.commit()
    return task


async def test_request_merge_creates_one_pending_approval_and_notifies(
    world: World, repo: Path, remote: Path, tmp_path: Path
) -> None:
    task = await point_project_at(world, repo)
    worktree = Worktrees(repo, tmp_path / "worktrees").create(task.id, task.title)
    commit_file(worktree.path, "work.txt")
    before = (refs(repo), refs(remote))

    async with world.sessions() as db:
        first = await request_merge(db, world.clock, task.id)
        again = await request_merge(db, world.clock, task.id)

    assert again.id == first.id
    assert [a.id for a in await world.service.list(ApprovalStatus.PENDING)] == [first.id]
    assert first.type == MERGE_ACTION
    assert first.task_id == task.id
    assert first.payload["branch"] == worktree.branch
    async with world.sessions() as db:
        subjects = list(await db.scalars(select(Notification.subject)))
    assert subjects == [f"approval:{first.id}"]
    assert (refs(repo), refs(remote)) == before


async def test_request_merge_without_a_task_branch_is_a_work_error(
    world: World, repo: Path
) -> None:
    task = await point_project_at(world, repo)

    async with world.sessions() as db:
        with pytest.raises(WorkError, match="no single branch"):
            await request_merge(db, world.clock, task.id)
        with pytest.raises(WorkError, match="no task 999"):
            await request_merge(db, world.clock, 999)

    assert await world.service.list() == []
