"""The CEO creates a department and its head unasked; the head staffs it within the cap."""

from labhq.db.enums import AgentStatus, DepartmentStatus
from labhq.db.models import Agent, Approval, Department
from tests.departments.conftest import Research, agents_of

MEMBERS = [
    {"key": "a", "role": "worker", "title": "Analyst", "adapter": "fake"},
    {"key": "b", "role": "worker", "title": "Writer", "adapter": "fake"},
]


async def test_the_ceo_creates_a_department_with_an_active_head_and_no_approval(
    research: Research,
) -> None:
    org = research.org
    department = await org.get(Department, research.department)
    head = await org.get(Agent, research.head)
    assert (department.kind, department.status) == ("research", DepartmentStatus.ACTIVE)
    assert (head.role, head.reports_to, head.status) == ("head", org.ceo, AgentStatus.ACTIVE)
    assert (head.project_id, head.department_id) == (None, department.id)
    # A folder under the data directory, which is not a git repository.
    assert research.folder.is_dir()
    assert research.folder.parent.name == "departments"
    assert not (research.folder / ".git").exists()
    assert await org.approvals() == []


async def test_the_head_staffs_its_department_within_the_cap(research: Research) -> None:
    org = research.org
    answer = await org.call("staff_department", research.head, members=MEMBERS)
    assert answer.startswith("Team created")
    workers = [agent for agent in await agents_of(research) if agent.role == "worker"]
    assert [worker.reports_to for worker in workers] == [research.head] * 2
    assert all(worker.status is AgentStatus.ACTIVE for worker in workers)
    # They inherit the department, so their prompt and tools find it.
    assert workers[0].config["department"]["kind"] == "research"
    assert "write_document" in workers[0].config["tools"]
    assert await org.all(Approval) == []


async def test_a_team_past_the_cap_is_refused(research: Research) -> None:
    org = research.org
    async with org.sessions() as db:
        head = await db.get_one(Agent, research.head)
        head.config = {**head.config, "max_team_size": 1}
        await db.commit()
    answer = await org.call("staff_department", research.head, members=MEMBERS)
    assert answer.startswith("Refused:")
    assert "cap of 1" in answer
    assert [a.role for a in await agents_of(research)] == ["head"]


async def test_the_ceo_can_staff_a_head_with_the_existing_tools(research: Research) -> None:
    org = research.org
    answer = await org.call("staff_team", org.ceo, manager=research.head, members=MEMBERS)
    assert answer.startswith("Team created under agent")
    created = await org.call(
        "create_agent", org.ceo, manager=research.head, role="worker", title="Clerk", adapter="fake"
    )
    assert "created" in created
    assert len(await agents_of(research)) == 4


async def test_a_worker_cannot_report_to_a_manager_but_can_to_a_head(research: Research) -> None:
    org = research.org
    answer = await org.call("staff_team", org.ceo, manager=org.manager, members=MEMBERS)
    assert answer.startswith("Refused:")
    assert "reports to" in answer


async def test_unknown_kinds_and_duplicate_names_are_refused(research: Research) -> None:
    org = research.org
    unknown = await org.call("create_department", org.ceo, name="Odd", kind="astrology")
    assert "no department kind 'astrology'" in unknown
    twice = await org.call("create_department", org.ceo, name="Research", kind="general")
    assert "already exists" in twice
    assert len(list(await org.all(Department))) == 1


async def test_the_budget_stays_under_the_owners_ceiling(research: Research) -> None:
    org = research.org
    ok = await org.call("set_budget", org.ceo, scope="department", id="Research", micros=1_000_000)
    assert "department Research" in ok
    refused = await org.call(
        "create_department", org.ceo, name="Big", kind="general", budget_micros=9_000_000
    )
    assert "above the owner's ceiling" in refused
    assert {row.name for row in await org.all(Department)} == {"Research"}
    assert (await org.get(Department, research.department)).budget_micros == 1_000_000


async def test_list_departments_names_the_kinds(research: Research) -> None:
    answer = await research.org.call("list_departments", research.org.ceo)
    assert "Research" in answer
    assert "Kinds you can create:" in answer
    assert "marketing" in answer
