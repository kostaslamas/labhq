"""The CEO's tools and the manager's team proposal leave approvals pending (plan §10)."""

from labhq.db.enums import AgentStatus, ApprovalStatus, RiskClass, RunStatus
from labhq.db.models import Agent, Project, Run, RunEvent
from labhq.hierarchy import CREATE_TEAM
from tests.roles.conftest import Org

NEW_PROJECT = "blog"
CEO_ORG_TOOLS = (
    "discover_projects",
    "add_project",
    "adopt_session",
    "assign_saved_session",
    "staff_team",
    "create_agent",
    "request_merge",
    "start_meeting",
    "set_priority",
    "set_budget",
)


async def add_project(org: Org, name: str) -> None:
    now = org.clock.now()
    async with org.sessions() as db:
        db.add(Project(name=name, repo_path=f"/srv/{name}", created_at=now, updated_at=now))
        await db.commit()


async def test_assign_manager_starts_the_manager_without_an_approval(org: Org) -> None:
    await add_project(org, NEW_PROJECT)

    answer = await org.call("assign_manager", org.ceo, project=NEW_PROJECT)

    assert await org.approvals() == []
    [manager] = [
        agent
        for agent in await org.all(Agent)
        if agent.role == "manager" and agent.title == "blog manager"
    ]
    assert (manager.reports_to, manager.status) == (org.ceo, AgentStatus.ACTIVE)
    assert f"Agent {manager.id} now manages {NEW_PROJECT}" in answer


async def test_assign_manager_refuses_a_project_that_has_one(org: Org) -> None:
    answer = await org.call("assign_manager", org.ceo, project="site")
    assert answer.startswith("Refused:")
    assert "already has manager" in answer
    assert await org.approvals() == []


async def test_list_projects_names_each_projects_manager(org: Org) -> None:
    answer = await org.call("list_projects", org.ceo)
    assert f"site (id {org.site}, active): manager agent {org.manager} (active)" in answer
    assert f"shop (id {org.shop}, active): manager agent {org.shop_manager}" in answer


async def test_ceo_can_list_run_status_and_named_tmux_panes(org: Org) -> None:
    now = org.clock.now()
    async with org.sessions() as db:
        run = Run(
            agent_id=org.ceo,
            adapter="tmux",
            status=RunStatus.SUCCEEDED,
            session_id_after="codex:session-id",
            created_at=now,
        )
        db.add(run)
        await db.flush()
        db.add(
            RunEvent(
                run_id=run.id,
                seq=1,
                kind="agent",
                payload={"kind": "codex"},
                created_at=now,
            )
        )
        other = Run(
            agent_id=org.ceo,
            adapter="tmux",
            status=RunStatus.SUCCEEDED,
            session_id_after="claude-code:other-id",
            created_at=now,
        )
        db.add(other)
        await db.flush()
        db.add(
            RunEvent(
                run_id=other.id,
                seq=1,
                kind="agent",
                payload={"kind": "claude-code"},
                created_at=now,
            )
        )
        await db.commit()

    answer = await org.call("list_agent_sessions", org.ceo)

    assert f"agent {org.ceo} (ceo" in answer
    assert f"run {other.id} succeeded, tmux names ceo_claude, ceo_codex" in answer
    assert "session-id" not in answer


async def test_propose_team_leaves_a_pending_heavy_create_team_approval(org: Org) -> None:
    before = len(await org.all(Agent))
    members = [
        {"key": "qa", "role": "lead", "title": "QA lead", "adapter": "fake"},
        {"key": "t1", "role": "worker", "title": "Tester", "adapter": "fake", "reports_to": "qa"},
    ]

    answer = await org.call("propose_team", org.manager, members=members)

    [approval] = await org.approvals()
    assert (approval.type, approval.risk_class) == (CREATE_TEAM, RiskClass.HEAVY)
    assert approval.status is ApprovalStatus.PENDING
    assert approval.payload["manager_id"] == org.manager
    assert len(await org.all(Agent)) == before
    assert "no agent exists until the owner approves" in answer


async def test_propose_team_proposes_for_the_caller_whatever_it_passes(org: Org) -> None:
    member = {"key": "x", "role": "lead", "title": "Lead", "adapter": "fake"}
    answer = await org.call(
        "propose_team", org.manager, members=[member], manager_id=org.shop_manager
    )
    assert "Invalid arguments" in answer
    assert await org.approvals() == []


async def test_a_bad_proposal_is_refused_with_its_reason(org: Org) -> None:
    member = {"key": "w", "role": "worker", "title": "Dev", "adapter": "fake"}
    answer = await org.call("propose_team", org.manager, members=[member])
    assert answer.startswith("Invalid arguments") or answer.startswith("Refused:")
    assert "reports to" in answer
    assert await org.approvals() == []


def test_each_role_sees_its_own_org_tools(org: Org) -> None:
    def names(role: str) -> set[str]:
        return {spec.name for spec in org.tools.for_agent(role, {})}

    assert names("ceo") == {
        "list_departments",
        "create_department",
        "delegate_department_task",
        "list_projects",
        "list_agent_sessions",
        "assign_manager",
        "delegate_task",
        "task_overview",
        "review_task",
        *CEO_ORG_TOOLS,
        "report_to_owner",
        "owner_decision",
        "send_control_key",
    }
    assert names("manager") == {
        "propose_team",
        "send_control_key",
        "create_task",
        "assign_task",
        "task_overview",
        "report_task",
        "review_task",
    }
    assert names("lead") == {
        "send_control_key",
        "create_task",
        "assign_task",
        "task_overview",
        "report_task",
        "review_task",
    }
    assert names("worker") == {"task_overview", "report_task"}
