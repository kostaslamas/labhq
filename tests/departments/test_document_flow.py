"""A department task delivers a document without git: head reviews it, then the CEO accepts."""

from pathlib import Path

from labhq.adapters import default_registry
from labhq.cli.workspace import WorkspaceRunService
from labhq.db.enums import TaskStatus
from labhq.db.models import Notification, Task
from labhq.settings import Settings
from tests.departments.conftest import Research, agents_of

WORKER = {"key": "w", "role": "worker", "title": "Analyst", "adapter": "fake"}


async def _task(research: Research, title: str) -> Task:
    return next(task for task in await research.org.all(Task) if task.title == title)


async def _worker(research: Research) -> int:
    await research.org.call("staff_department", research.head, members=[WORKER])
    return next(a.id for a in await agents_of(research) if a.role == "worker")


async def test_a_document_task_completes_without_git(research: Research) -> None:
    org = research.org
    worker = await _worker(research)
    delegated = await org.call(
        "delegate_department_task",
        org.ceo,
        department="Research",
        title="Market scan",
        deliverable="document",
    )
    assert "delegated" in delegated
    root = await _task(research, "Market scan")
    assert (root.project_id, root.department_id) == (None, research.department)
    assert root.assignee_id == research.head

    made = await org.call(
        "create_task", research.head, title="Collect sources", parent=root.id, assignee=worker
    )
    assert made.startswith("Task #"), made
    child = await _task(research, "Collect sources")
    assert (child.deliverable, child.department_id) == ("document", research.department)

    # The report is refused until the file exists.
    early = await org.call("report_task", worker, task=child.id, summary="Done")
    assert "write_document" in early
    saved = await org.call(
        "write_document", worker, task=child.id, content="# Sources\n- a\n", name="sources.md"
    )
    assert "documents/T" in saved
    child = await org.get(Task, child.id)
    assert child.deliverable_ref is not None
    assert (research.folder / child.deliverable_ref).read_text() == "# Sources\n- a\n"

    await org.call("report_task", worker, task=child.id, summary="Sources collected")
    assert (await org.get(Task, child.id)).status is TaskStatus.IN_REVIEW
    await org.call("review_task", research.head, task=child.id, accept=True, feedback="Good")
    assert (await org.get(Task, child.id)).status is TaskStatus.DONE

    await org.call("write_document", research.head, task=root.id, content="# Scan\n")
    await org.call("report_task", research.head, task=root.id, summary="Scan ready")
    assert (await org.get(Task, root.id)).status is TaskStatus.IN_REVIEW
    # The CEO accepts a department's task itself: it does not wait for the owner.
    accepted = await org.call("review_task", org.ceo, task=root.id, accept=True, feedback="Useful")
    assert accepted == f"Task #{root.id} is done."
    assert (await org.get(Task, root.id)).status is TaskStatus.DONE
    (report,) = await org.all(Notification)
    assert "Research delivered" in report.body

    # Nothing in the department folder is a repository or a worktree.
    assert not list(research.folder.rglob(".git"))
    assert sorted(path.parent.name for path in research.folder.rglob("T*")) == [
        "documents",
        "documents",
    ]


async def test_a_document_name_cannot_leave_the_folder(research: Research) -> None:
    org = research.org
    await org.call(
        "delegate_department_task",
        org.ceo,
        department="Research",
        title="Memo",
        deliverable="document",
    )
    root = await _task(research, "Memo")
    refused = await org.call(
        "write_document", research.head, task=root.id, content="x", name="../../escape.md"
    )
    assert refused.startswith("Refused:")
    assert not (research.folder.parent.parent / "escape.md").exists()


async def test_a_report_deliverable_needs_no_file(research: Research) -> None:
    org = research.org
    await org.call(
        "delegate_department_task",
        org.ceo,
        department="Research",
        title="Brief",
        deliverable="decision",
    )
    root = await _task(research, "Brief")
    await org.call("report_task", research.head, task=root.id, summary="Decision: go.")
    await org.call("review_task", org.ceo, task=root.id, accept=True, feedback="Agreed")
    assert (await org.get(Task, root.id)).status is TaskStatus.DONE
    (report,) = await org.all(Notification)
    assert "Decision: go." in report.body


async def test_a_deliverable_the_kind_does_not_deliver_is_refused(research: Research) -> None:
    org = research.org
    answer = await org.call(
        "delegate_department_task",
        org.ceo,
        department="Research",
        title="Code",
        deliverable="branch",
    )
    assert answer.startswith("Refused:")


async def test_department_tasks_never_get_a_worktree(research: Research) -> None:
    org = research.org
    await org.call(
        "delegate_department_task",
        org.ceo,
        department="Research",
        title="Memo",
        deliverable="document",
    )
    root = await _task(research, "Memo")
    service = WorkspaceRunService(
        org.sessions, clock=org.clock, registry=default_registry, settings=Settings()
    )
    folder, plain = await service._task_workspace(root.id)
    assert (folder, plain) == (research.folder, True)
    assert not (Settings().data_dir / "worktrees").exists()
    assert isinstance(folder, Path)
