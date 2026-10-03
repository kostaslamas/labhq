from datetime import timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.api.app import create_app
from labhq.api.deps import ResolverRegistry
from labhq.api.projects import router
from labhq.api.routes import RouterRegistry
from labhq.api.settings import ApiSettings
from labhq.budgets import BudgetSettings, Decision, decide
from labhq.cli.context import Context
from labhq.clock import FakeClock
from labhq.db.enums import AgentStatus, ApprovalStatus, RiskClass, TaskStatus
from labhq.db.models import Agent, Approval, CostEvent, Project, Run, Task
from tests.api.conftest import OWNER_HEADER

BUDGET = 1_000_000
SHA = "a" * 40


@pytest.fixture
async def client(context: Context, resolvers: ResolverRegistry, api_settings: ApiSettings) -> Any:
    routers = RouterRegistry()
    routers.register(router)
    app = create_app(context, routers=routers, resolvers=resolvers, settings=api_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={OWNER_HEADER: "owner"},
    ) as http:
        yield http


async def add_project(
    session: AsyncSession, clock: FakeClock, name: str, budget: int | None = None
) -> Project:
    now = clock.now()
    project = Project(
        name=name, repo_path=f"/srv/{name}", budget_micros=budget, created_at=now, updated_at=now
    )
    session.add(project)
    await session.flush()
    return project


async def add_agent(
    session: AsyncSession,
    clock: FakeClock,
    project: Project,
    title: str,
    reports_to: int | None = None,
    budget: int | None = None,
) -> Agent:
    now = clock.now()
    agent = Agent(
        project_id=project.id,
        role="worker",
        title=title,
        adapter="fake",
        reports_to=reports_to,
        budget_micros=budget,
        status=AgentStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    session.add(agent)
    await session.flush()
    return agent


async def add_task(
    session: AsyncSession,
    clock: FakeClock,
    project: Project,
    title: str,
    status: TaskStatus = TaskStatus.TODO,
) -> Task:
    now = clock.now()
    task = Task(project_id=project.id, title=title, status=status, created_at=now, updated_at=now)
    session.add(task)
    await session.flush()
    return task


async def spend(session: AsyncSession, clock: FakeClock, agent: Agent, micros: int) -> None:
    session.add(
        CostEvent(
            agent_id=agent.id,
            project_id=agent.project_id,
            cost_micros=micros,
            created_at=clock.now(),
        )
    )
    await session.flush()


@pytest.mark.parametrize(
    ("spent", "state"),
    [
        (0, "allow"),
        (799_999, "allow"),
        (800_000, "warn"),
        (999_999, "warn"),
        (1_000_000, "stop"),
        (1_500_000, "stop"),
    ],
)
async def test_card_state_matches_the_budget_module_at_80_and_100_percent(
    client: httpx.AsyncClient,
    session: AsyncSession,
    clock: FakeClock,
    spent: int,
    state: str,
) -> None:
    project = await add_project(session, clock, "atlas", BUDGET)
    agent = await add_agent(session, clock, project, "Worker")
    await spend(session, clock, agent, spent)
    await session.commit()

    card = (await client.get("/api/projects")).json()["items"][0]

    assert card["budget"]["spent_micros"] == spent
    assert card["budget"]["budget_micros"] == BUDGET
    assert card["budget"]["state"] == state
    assert Decision(state) is decide(spent, BUDGET, BudgetSettings())
    assert card["budget"]["used_percent"] == spent * 100 // BUDGET


async def test_every_project_has_a_card_even_without_budget_or_work(
    client: httpx.AsyncClient, session: AsyncSession, clock: FakeClock
) -> None:
    for name in ("alpha", "beta", "gamma"):
        await add_project(session, clock, name)
    await session.commit()

    cards: list[dict[str, Any]] = []
    cursor = None
    while True:
        params = {"cursor": cursor} if cursor else {}
        body = (await client.get("/api/projects", params=params)).json()
        cards += body["items"]
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert [card["name"] for card in cards] == ["alpha", "beta", "gamma"]
    assert all(card["budget"]["budget_micros"] is None for card in cards)
    assert all(card["budget"]["state"] == "allow" for card in cards)
    assert all(card["budget"]["used_percent"] is None for card in cards)
    assert all(card["latest_deliverable"] is None for card in cards)
    assert [c["status"] for c in cards[0]["open_tasks"]] == [
        "backlog",
        "todo",
        "in_progress",
        "in_review",
        "blocked",
    ]


async def test_card_counts_open_tasks_only(
    client: httpx.AsyncClient, session: AsyncSession, clock: FakeClock
) -> None:
    project = await add_project(session, clock, "atlas")
    other = await add_project(session, clock, "beacon")
    for status in (TaskStatus.TODO, TaskStatus.TODO, TaskStatus.BLOCKED, TaskStatus.DONE):
        await add_task(session, clock, project, "t", status)
    await add_task(session, clock, other, "elsewhere", TaskStatus.IN_PROGRESS)
    await session.commit()

    cards = {c["name"]: c for c in (await client.get("/api/projects")).json()["items"]}

    counts = {t["status"]: t["count"] for t in cards["atlas"]["open_tasks"]}
    assert counts == {"backlog": 0, "todo": 2, "in_progress": 0, "in_review": 0, "blocked": 1}


async def test_spend_before_the_period_does_not_count(
    client: httpx.AsyncClient, session: AsyncSession, clock: FakeClock
) -> None:
    project = await add_project(session, clock, "atlas", BUDGET)
    agent = await add_agent(session, clock, project, "Worker")
    await spend(session, clock, agent, 900_000)
    await session.commit()
    clock.advance(timedelta(days=40))

    card = (await client.get("/api/projects")).json()["items"][0]

    assert card["budget"]["spent_micros"] == 0
    assert card["budget"]["state"] == "allow"


async def test_the_team_is_a_tree_along_reports_to_with_spend_per_agent(
    client: httpx.AsyncClient, session: AsyncSession, clock: FakeClock
) -> None:
    project = await add_project(session, clock, "atlas", BUDGET)
    manager = await add_agent(session, clock, project, "Manager")
    lead = await add_agent(session, clock, project, "Lead", manager.id, 500_000)
    worker = await add_agent(session, clock, project, "Worker", lead.id)
    deep = await add_agent(session, clock, project, "Intern", worker.id)
    await add_agent(session, clock, project, "Second lead", manager.id)
    await spend(session, clock, lead, 400_000)
    await spend(session, clock, deep, 100)
    await session.commit()

    view = (await client.get(f"/api/projects/{project.id}")).json()

    [root] = view["team"]
    assert root["title"] == "Manager"
    assert [r["title"] for r in root["reports"]] == ["Lead", "Second lead"]
    lead_node = root["reports"][0]
    assert lead_node["budget"] == {
        "budget_micros": 500_000,
        "spent_micros": 400_000,
        "state": "warn",
        "used_percent": 80,
    }
    intern = lead_node["reports"][0]["reports"][0]
    assert intern["title"] == "Intern"
    assert intern["budget"]["spent_micros"] == 100
    assert view["budget"]["spent_micros"] == 400_100


async def test_a_reporting_cycle_does_not_hide_agents_or_loop(
    client: httpx.AsyncClient, session: AsyncSession, clock: FakeClock
) -> None:
    project = await add_project(session, clock, "atlas")
    first = await add_agent(session, clock, project, "First")
    second = await add_agent(session, clock, project, "Second", first.id)
    first.reports_to = second.id
    await session.commit()

    view = (await client.get(f"/api/projects/{project.id}")).json()

    assert sorted(node["title"] for node in view["team"]) == ["First", "Second"]


async def test_deliverables_carry_branch_commits_and_cost(
    client: httpx.AsyncClient, session: AsyncSession, clock: FakeClock
) -> None:
    project = await add_project(session, clock, "atlas")
    agent = await add_agent(session, clock, project, "Worker")
    done = await add_task(session, clock, project, "Add a HELLO file", TaskStatus.DONE)
    await add_task(session, clock, project, "Still open", TaskStatus.IN_PROGRESS)
    for micros in (1_250_000, 7):
        run = Run(agent_id=agent.id, task_id=done.id, adapter="fake", created_at=clock.now())
        session.add(run)
        await session.flush()
        session.add(
            CostEvent(
                run_id=run.id,
                agent_id=agent.id,
                project_id=project.id,
                cost_micros=micros,
                created_at=clock.now(),
            )
        )
    for status, commit in ((ApprovalStatus.EXECUTED, SHA), (ApprovalStatus.PENDING, "b" * 40)):
        session.add(
            Approval(
                type="push",
                risk_class=RiskClass.HEAVY,
                status=status,
                payload={"commit": commit},
                task_id=done.id,
                executed_at=clock.now(),
                created_at=clock.now(),
            )
        )
    await session.commit()

    view = (await client.get(f"/api/projects/{project.id}")).json()
    card = (await client.get("/api/projects")).json()["items"][0]

    assert view["deliverables_total"] == 1
    [deliverable] = view["deliverables"]
    assert deliverable["task_id"] == done.id
    assert deliverable["branch"] == f"labhq/task-{done.id}-add-a-hello-file"
    assert deliverable["commits"] == [SHA]
    assert deliverable["cost_micros"] == 1_250_007
    assert card["latest_deliverable"] == deliverable
    counts = {t["status"]: t["count"] for t in view["tasks"]}
    assert counts["done"] == 1
    assert counts["in_progress"] == 1


async def test_money_crosses_the_api_as_integers(
    client: httpx.AsyncClient, session: AsyncSession, clock: FakeClock
) -> None:
    project = await add_project(session, clock, "atlas", 3)
    agent = await add_agent(session, clock, project, "Worker", budget=7)
    await spend(session, clock, agent, 2)
    await session.commit()

    text = (await client.get(f"/api/projects/{project.id}")).text
    view = (await client.get(f"/api/projects/{project.id}")).json()

    for budget in (view["budget"], view["team"][0]["budget"]):
        for field in ("budget_micros", "spent_micros", "used_percent"):
            assert type(budget[field]) is int
    assert '"spent_micros":2' in text
    assert view["budget"]["used_percent"] == 66
    assert view["policy"]["warn_percent"] == 80
    assert view["policy"]["stop_percent"] == 100


async def test_unknown_project_is_a_404_envelope(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/projects/999")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "project_not_found"


async def test_projects_need_a_session(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/projects", headers={OWNER_HEADER: ""})

    assert response.status_code == 401
