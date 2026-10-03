"""A team is one heavy approval; the agents exist only once a human approved it, within the cap."""

from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from labhq.callcenter.actions import decide
from labhq.db.enums import AgentStatus, ApprovalStatus, RiskClass
from labhq.db.models import Agent
from labhq.hierarchy import CREATE_TEAM, TEAM_SIZE_KEY, HierarchyError, TeamSizeError
from tests.hierarchy.conftest import CAP, World

TEAM: list[dict[str, Any]] = [
    {"key": "back", "role": "lead", "title": "Backend lead", "adapter": "fake"},
    {"key": "dev", "role": "worker", "title": "Developer", "adapter": "fake", "reports_to": "back"},
]


def members(count: int) -> list[dict[str, Any]]:
    lead = {"key": "lead", "role": "lead", "title": "Lead", "adapter": "fake"}
    workers = [
        {
            "key": f"w{n}",
            "role": "worker",
            "title": f"W{n}",
            "adapter": "fake",
            "reports_to": "lead",
        }
        for n in range(count - 1)
    ]
    return [lead, *workers]


async def test_a_proposal_is_one_pending_heavy_approval_and_no_agent(world: World) -> None:
    manager = await world.active_manager()
    before = await world.agents()

    approval = await world.hierarchy.propose_team(manager.id, TEAM)

    assert (approval.type, approval.risk_class, approval.status) == (
        CREATE_TEAM,
        RiskClass.HEAVY,
        ApprovalStatus.PENDING,
    )
    assert approval.requested_by_agent_id == manager.id
    assert approval.payload["manager_id"] == manager.id
    assert [member["key"] for member in approval.payload["members"]] == ["back", "dev"]
    assert [approval.id for approval in await world.approvals.list(ApprovalStatus.PENDING)] == [
        approval.id
    ]
    assert len(await world.agents()) == len(before)


async def test_approving_a_proposal_creates_the_team_with_its_reporting_lines(
    world: World,
) -> None:
    manager = await world.active_manager()
    approval = await world.hierarchy.propose_team(manager.id, TEAM)

    executed = await world.approvals.approve(approval.id, decider="operator", confirmation="cli")

    assert executed.status is ApprovalStatus.EXECUTED
    assert executed.execution is not None
    ids = executed.execution["agents"]
    lead, dev = await world.agent(ids["back"]), await world.agent(ids["dev"])
    assert (lead.role, lead.title, lead.reports_to) == ("lead", "Backend lead", manager.id)
    assert (dev.role, dev.title, dev.reports_to) == ("worker", "Developer", lead.id)
    assert {lead.status, dev.status} == {AgentStatus.ACTIVE}
    assert {lead.project_id, dev.project_id} == {manager.project_id}


async def test_a_proposal_past_the_cap_is_refused(world: World) -> None:
    manager = await world.active_manager()

    with pytest.raises(TeamSizeError, match="team-size cap"):
        await world.hierarchy.propose_team(manager.id, members(CAP + 1))

    assert await world.approvals.list(ApprovalStatus.PENDING) == []


async def test_a_proposal_up_to_the_cap_is_accepted(world: World) -> None:
    manager = await world.active_manager()

    approval = await world.hierarchy.propose_team(manager.id, members(CAP))

    assert approval.status is ApprovalStatus.PENDING


async def test_the_managers_config_overrides_the_cap(world: World) -> None:
    manager = await world.active_manager()
    async with world.sessions() as db:
        row = await db.get_one(Agent, manager.id)
        row.config = {TEAM_SIZE_KEY: 1}
        await db.commit()

    with pytest.raises(TeamSizeError, match="cap of 1"):
        await world.hierarchy.propose_team(manager.id, TEAM)


async def test_an_approved_team_that_would_pass_the_cap_at_execution_creates_nothing(
    world: World,
) -> None:
    manager = await world.active_manager()
    first = await world.hierarchy.propose_team(manager.id, members(2))
    second = await world.hierarchy.propose_team(manager.id, members(2))
    await world.approvals.approve(first.id, decider="operator", confirmation="cli")
    before = await world.agents()

    # The team grew between the proposal and its approval: 2 + 2 is past a cap of 3.
    failed = await world.approvals.approve(second.id, decider="operator", confirmation="cli")

    assert failed.status is ApprovalStatus.EXECUTION_FAILED
    assert failed.execution is not None
    assert "team-size cap" in failed.execution["message"]
    assert [agent.id for agent in await world.agents()] == [agent.id for agent in before]


async def test_a_proposal_with_a_line_outside_the_table_is_refused(world: World) -> None:
    manager = await world.active_manager()
    worker_under_manager = [{"key": "w", "role": "worker", "title": "W", "adapter": "fake"}]

    with pytest.raises(ValidationError, match="reports to"):
        await world.hierarchy.propose_team(manager.id, worker_under_manager)

    assert await world.approvals.list(ApprovalStatus.PENDING) == []


async def test_only_an_active_manager_may_propose(world: World) -> None:
    assignment = await world.hierarchy.assign_manager(world.project)
    ceo = await world.hierarchy.ensure_ceo()

    with pytest.raises(HierarchyError, match="not active"):
        await world.hierarchy.propose_team(assignment.manager.id, TEAM)
    with pytest.raises(HierarchyError, match="not a manager"):
        await world.hierarchy.propose_team(ceo.id, TEAM)


async def test_the_voice_decide_tool_cannot_approve_create_team(world: World) -> None:
    manager = await world.active_manager()
    approval = await world.hierarchy.propose_team(manager.id, TEAM)

    async with world.sessions() as db:
        answer = await decide(db, world.clock, f"A{approval.id}", "approve")
        team = await db.scalars(select(Agent).where(Agent.reports_to == manager.id))

        assert "passkey" in answer
        assert list(team) == []
    row = await world.approvals.get(approval.id)
    assert (row.status, row.decided_by, row.execution) == (ApprovalStatus.PENDING, None, None)
