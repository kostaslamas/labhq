"""The CEO exists on demand and gives each project a manager, pending a light approval."""

import pytest

from labhq.db.enums import AgentStatus, ApprovalStatus, RiskClass
from labhq.hierarchy import CREATE_AGENT, Hierarchy, HierarchyError, HierarchySettings
from labhq.work import WorkError
from tests.hierarchy.conftest import ADAPTERS, World


async def test_ensure_ceo_creates_one_ceo_without_project_or_manager(world: World) -> None:
    first = await world.hierarchy.ensure_ceo()
    again = await world.hierarchy.ensure_ceo()

    assert again.id == first.id
    (ceo,) = await world.agents()
    assert (ceo.role, ceo.project_id, ceo.reports_to) == ("ceo", None, None)
    assert ceo.status is AgentStatus.ACTIVE


async def test_assign_manager_creates_a_manager_pending_a_light_approval(world: World) -> None:
    assignment = await world.hierarchy.assign_manager(world.project)

    ceo = await world.hierarchy.ensure_ceo()
    manager = await world.agent(assignment.manager.id)
    assert (manager.role, manager.reports_to) == ("manager", ceo.id)
    assert manager.project_id is not None
    assert manager.status is AgentStatus.PENDING_APPROVAL
    approval = assignment.approval
    assert approval is not None
    assert (approval.type, approval.risk_class, approval.status) == (
        CREATE_AGENT,
        RiskClass.LIGHT,
        ApprovalStatus.PENDING,
    )
    assert approval.payload == {"agent_id": manager.id}
    assert approval.requested_by_agent_id == ceo.id


async def test_approving_the_new_manager_makes_it_active(world: World) -> None:
    assignment = await world.hierarchy.assign_manager(world.project)
    assert assignment.approval is not None
    world.clock.advance(60)

    approved = await world.approvals.approve(
        assignment.approval.id, decider="operator", confirmation="cli"
    )

    assert approved.status is ApprovalStatus.EXECUTED
    manager = await world.agent(assignment.manager.id)
    assert manager.status is AgentStatus.ACTIVE
    assert manager.updated_at == world.clock.now()


async def test_voice_may_approve_a_new_manager_because_it_is_light(world: World) -> None:
    assignment = await world.hierarchy.assign_manager(world.project)
    assert assignment.approval is not None

    await world.approvals.approve(assignment.approval.id, decider="caller", confirmation="voice")

    assert (await world.agent(assignment.manager.id)).status is AgentStatus.ACTIVE


async def test_without_new_agent_approval_the_manager_starts_active(
    world: World, settings: HierarchySettings
) -> None:
    hierarchy = Hierarchy(
        world.sessions,
        clock=world.clock,
        adapters=ADAPTERS,
        approvals=world.approvals,
        settings=settings.model_copy(update={"approve_new_agents": False}),
    )

    assignment = await hierarchy.assign_manager(world.project)

    assert assignment.approval is None
    assert (await world.agent(assignment.manager.id)).status is AgentStatus.ACTIVE
    assert await world.approvals.list() == []


async def test_a_project_with_a_manager_gets_no_second_one(world: World) -> None:
    await world.hierarchy.assign_manager(world.project)

    with pytest.raises(HierarchyError, match="already has manager"):
        await world.hierarchy.assign_manager(world.project)

    assert [agent.role for agent in await world.agents()] == ["ceo", "manager"]


async def test_a_rejected_manager_is_retired_and_replaced(world: World) -> None:
    first = await world.hierarchy.assign_manager(world.project)
    assert first.approval is not None
    await world.approvals.reject(first.approval.id, decider="operator", confirmation="cli")

    second = await world.hierarchy.assign_manager(world.project)

    assert (await world.agent(first.manager.id)).status is AgentStatus.RETIRED
    assert second.manager.status is AgentStatus.PENDING_APPROVAL


async def test_an_unknown_project_gets_no_manager(world: World) -> None:
    with pytest.raises(WorkError, match="no project"):
        await world.hierarchy.assign_manager("nope")
