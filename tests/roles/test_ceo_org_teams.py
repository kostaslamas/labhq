"""The CEO staffs a team for a manager without an approval, up to the manager's cap."""

from labhq.db.enums import AgentStatus
from labhq.db.models import Agent
from labhq.hierarchy import TEAM_SIZE_KEY
from tests.roles.conftest import Org

LEAD = {"key": "ops", "role": "lead", "title": "Ops lead", "adapter": "fake"}
WORKER = {"key": "dev", "role": "worker", "title": "Dev", "adapter": "fake", "reports_to": "ops"}


async def team_of_shop(org: Org) -> list[Agent]:
    return [a for a in await org.all(Agent) if a.project_id == org.shop]


async def test_the_ceo_staffs_a_team_with_no_approval(org: Org) -> None:
    before = len(await team_of_shop(org))

    answer = await org.call("staff_team", org.ceo, manager=org.shop_manager, members=[LEAD, WORKER])

    assert await org.approvals() == []
    created = (await team_of_shop(org))[before:]
    assert [(a.role, a.status) for a in created] == [
        ("lead", AgentStatus.ACTIVE),
        ("worker", AgentStatus.ACTIVE),
    ]
    assert created[0].reports_to == org.shop_manager
    assert created[1].reports_to == created[0].id
    assert "Team created" in answer


async def test_a_team_above_the_cap_is_refused_and_creates_nobody(org: Org) -> None:
    async with org.sessions() as db:
        manager = await db.get_one(Agent, org.shop_manager)
        manager.config = {TEAM_SIZE_KEY: 3}
        await db.commit()
    before = len(await team_of_shop(org))

    answer = await org.call("staff_team", org.ceo, manager=org.shop_manager, members=[LEAD, WORKER])

    assert answer.startswith("Refused:")
    assert "team-size cap of 3" in answer
    assert len(await team_of_shop(org)) == before


async def test_create_agent_adds_one_member_under_a_lead_within_the_cap(org: Org) -> None:
    answer = await org.call(
        "create_agent",
        org.ceo,
        manager=org.manager,
        role="worker",
        title="Second backend dev",
        adapter="fake",
        reports_to=org.lead,
    )

    [agent] = [a for a in await org.all(Agent) if a.title == "Second backend dev"]
    assert (agent.reports_to, agent.status, agent.project_id) == (
        org.lead,
        AgentStatus.ACTIVE,
        org.site,
    )
    assert await org.approvals() == []
    assert f"Agent {agent.id}" in answer


async def test_create_agent_refuses_a_member_of_another_team_and_a_full_team(org: Org) -> None:
    other = await org.call(
        "create_agent",
        org.ceo,
        manager=org.manager,
        role="worker",
        title="Stray",
        adapter="fake",
        reports_to=org.shop_worker,
    )
    assert other.startswith("Refused:")

    async with org.sessions() as db:
        (await db.get_one(Agent, org.manager)).config = {TEAM_SIZE_KEY: 4}
        await db.commit()
    full = await org.call(
        "create_agent", org.ceo, manager=org.manager, role="lead", title="One more", adapter="fake"
    )
    assert full.startswith("Refused:")
    assert "team-size cap of 4" in full


async def test_a_managers_own_proposal_still_waits_for_the_owner(org: Org) -> None:
    await org.call("propose_team", org.manager, members=[LEAD])

    [approval] = await org.approvals()
    assert (approval.type, approval.status) == ("create_team", "pending")
