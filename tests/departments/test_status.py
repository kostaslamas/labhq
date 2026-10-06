"""The Call Center's status answers include what departments reported."""

from labhq.callcenter.answers import reports
from labhq.db.models import Task
from tests.departments.conftest import Research


async def test_status_from_reports_includes_department_reports(research: Research) -> None:
    org = research.org
    await org.call(
        "delegate_department_task",
        org.ceo,
        department="Research",
        title="Pricing study",
        deliverable="decision",
    )
    task = next(task for task in await org.all(Task) if task.title == "Pricing study")
    await org.call("report_task", research.head, task=task.id, summary="Raise prices by five")

    async with org.sessions() as db:
        everything = await reports(db, org.clock)
        named = await reports(db, org.clock, "Research")
    for answer in (everything, named):
        assert "Reports in Research" in answer
        assert "Raise prices by five" in answer
        assert f"T{task.id}" in answer


async def test_a_department_without_reports_says_so(research: Research) -> None:
    async with research.org.sessions() as db:
        answer = await reports(db, research.org.clock, "Research")
    assert "In Research, nobody has reported yet" in answer
