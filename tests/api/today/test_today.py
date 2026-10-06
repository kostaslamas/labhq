from datetime import timedelta
from typing import Any

import httpx
import pytest

from labhq.api.app import create_app
from labhq.api.deps import ResolverRegistry
from labhq.api.routes import default_routers
from labhq.api.settings import ApiSettings
from labhq.budgets.periods import period_start
from labhq.budgets.settings import get_budget_settings
from labhq.cli.context import Context
from labhq.clock import FakeClock
from labhq.db.enums import (
    AgentStatus,
    ApprovalStatus,
    BudgetScope,
    QuestionStatus,
    RiskClass,
    RunStatus,
    TaskStatus,
)
from labhq.db.models import (
    Agent,
    AgentQuestion,
    Approval,
    BudgetWarning,
    CostEvent,
    HealthRule,
    Host,
    Incident,
    Project,
    Run,
    Task,
)

OWNER_HEADER = "X-Test-Owner"  # The header the parent conftest resolver reads.

COMMIT = "a" * 40
BRANCH = "labhq/task-1-add-hello"


@pytest.fixture
async def client(context: Context, resolvers: ResolverRegistry, api_settings: ApiSettings) -> Any:
    app = create_app(context, routers=default_routers, resolvers=resolvers, settings=api_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={OWNER_HEADER: "owner"},
    ) as client:
        yield client


async def seed(context: Context) -> dict[str, int]:
    """One delivered task, one agent that spent without delivering, and everything pending."""
    now = context.clock.now()
    async with context.sessions() as db:
        project = Project(name="atlas", repo_path="/r", created_at=now, updated_at=now)
        idle_project = Project(name="beacon", repo_path="/r2", created_at=now, updated_at=now)
        db.add_all([project, idle_project])
        await db.flush()
        worker = Agent(
            project_id=project.id,
            role="worker",
            title="Worker",
            adapter="fake",
            status=AgentStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        spender = Agent(
            project_id=idle_project.id,
            role="worker",
            title="Researcher",
            adapter="fake",
            status=AgentStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        db.add_all([worker, spender])
        await db.flush()
        done = Task(
            project_id=project.id,
            title="Add a HELLO file",
            status=TaskStatus.DONE,
            created_at=now - timedelta(hours=3),
            updated_at=now - timedelta(hours=1),
        )
        old = Task(
            project_id=project.id,
            title="Last week",
            status=TaskStatus.DONE,
            created_at=now - timedelta(days=9),
            updated_at=now - timedelta(days=8),
        )
        db.add_all([done, old])
        await db.flush()
        run = Run(
            agent_id=worker.id,
            task_id=done.id,
            adapter="fake",
            status=RunStatus.SUCCEEDED,
            created_at=now,
        )
        db.add(run)
        await db.flush()
        db.add_all(
            [
                CostEvent(
                    run_id=run.id,
                    agent_id=worker.id,
                    project_id=project.id,
                    cost_micros=1_250_000,
                    created_at=now - timedelta(hours=2),
                ),
                CostEvent(
                    agent_id=spender.id,
                    project_id=idle_project.id,
                    cost_micros=420_000,
                    created_at=now - timedelta(hours=2),
                ),
            ]
        )
        pushed = Approval(
            type="push",
            risk_class=RiskClass.HEAVY,
            status=ApprovalStatus.EXECUTED,
            payload={"branch": BRANCH, "commit": COMMIT},
            task_id=done.id,
            executed_at=now,
            created_at=now,
        )
        heavy = Approval(
            type="merge", risk_class=RiskClass.HEAVY, task_id=done.id, created_at=now, payload={}
        )
        light = Approval(
            type="assign_task",
            risk_class=RiskClass.LIGHT,
            created_at=now - timedelta(minutes=5),
            payload={},
        )
        db.add_all([pushed, heavy, light])
        question = AgentQuestion(
            agent_id=worker.id,
            task_id=done.id,
            question="Greek too?",
            fingerprint="f" * 64,
            status=QuestionStatus.PENDING,
            created_at=now,
        )
        host = Host(name="box", created_at=now, updated_at=now)
        db.add_all([question, host])
        await db.flush()
        rule = HealthRule(
            type="threshold",
            name="Disk almost full",
            reason="x",
            created_by="test",
            host_id=host.id,
            created_at=now,
            updated_at=now,
        )
        db.add(rule)
        await db.flush()
        db.add(Incident(rule_id=rule.id, host_id=host.id, opened_at=now))
        db.add(
            BudgetWarning(
                scope=BudgetScope.PROJECT,
                scope_id=project.id,
                period_start=period_start(get_budget_settings().period, now),
                spent_micros=850_000,
                budget_micros=1_000_000,
                created_at=now,
            )
        )
        await db.commit()
        return {"heavy": heavy.id, "light": light.id, "spender": spender.id, "done": done.id}


async def test_deliverables_carry_branch_commits_approvals_and_cost(
    client: httpx.AsyncClient, context: Context
) -> None:
    await seed(context)
    body = (await client.get("/api/today")).json()

    assert [item["title"] for item in body["deliverables"]] == ["Add a HELLO file"]
    delivered = body["deliverables"][0]
    assert delivered["project_name"] == "atlas"
    assert delivered["branch"] == BRANCH
    assert delivered["commit_count"] == 1
    assert delivered["cost_micros"] == 1_250_000
    assert [(a["type"], a["status"]) for a in delivered["approvals"]] == [("push", "executed")]


async def test_since_widens_the_window(client: httpx.AsyncClient, context: Context) -> None:
    await seed(context)
    since = (context.clock.now() - timedelta(days=30)).isoformat()
    body = (await client.get("/api/today", params={"since": since})).json()

    assert {item["title"] for item in body["deliverables"]} == {"Add a HELLO file", "Last week"}


async def test_needs_you_lists_heavy_approvals_first_and_counts_everything(
    client: httpx.AsyncClient, context: Context
) -> None:
    ids = await seed(context)
    needs = (await client.get("/api/today")).json()["needs_you"]

    assert [item["id"] for item in needs["approvals"]] == [ids["heavy"], ids["light"]]
    assert needs["approvals"][0]["project_name"] == "atlas"
    assert [item["question"] for item in needs["questions"]] == ["Greek too?"]
    assert [item["rule_name"] for item in needs["incidents"]] == ["Disk almost full"]
    warning = needs["budget_warnings"][0]
    assert (warning["name"], warning["spent_micros"], warning["budget_micros"]) == (
        "atlas",
        850_000,
        1_000_000,
    )
    assert needs["count"] == 2 + 1 + 1 + 1


async def test_spend_without_a_deliverable_is_a_warning_in_integer_micros(
    client: httpx.AsyncClient, context: Context
) -> None:
    ids = await seed(context)
    spend = (await client.get("/api/today")).json()["spend_without_output"]

    assert spend == [
        {
            "agent_id": ids["spender"],
            "agent_title": "Researcher",
            "project_id": spend[0]["project_id"],
            "project_name": "beacon",
            "cost_micros": 420_000,
        }
    ]
    assert isinstance(spend[0]["cost_micros"], int)


async def test_an_empty_database_answers_with_empty_lists(client: httpx.AsyncClient) -> None:
    body = (await client.get("/api/today")).json()

    assert body["deliverables"] == []
    assert body["spend_without_output"] == []
    assert body["needs_you"]["count"] == 0


async def test_no_running_work_is_exposed(client: httpx.AsyncClient, context: Context) -> None:
    await seed(context)
    body = (await client.get("/api/today")).json()

    assert set(body) == {
        "since",
        "until",
        "ceo_report",
        "deliverables",
        "needs_you",
        "spend_without_output",
    }


async def test_the_window_defaults_to_the_last_24_hours(
    client: httpx.AsyncClient, clock: FakeClock
) -> None:
    body = (await client.get("/api/today")).json()

    assert body["until"].startswith("2026-10-02T09:00:00")
    assert body["since"].startswith("2026-10-01T09:00:00")


async def test_today_needs_the_owner(
    context: Context, resolvers: ResolverRegistry, api_settings: ApiSettings
) -> None:
    app = create_app(context, routers=default_routers, resolvers=resolvers, settings=api_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as anonymous:
        assert (await anonymous.get("/api/today")).status_code == 401
