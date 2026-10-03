"""Adoption waits for the owner, then moves the agent at its turn end without two drivers."""

from pathlib import Path

import pytest
from sqlalchemy import select

from labhq.adoption import ADOPT_AGENT, NO_ISOLATION_WARNING, state_of
from labhq.adoption.discovery import is_alive
from labhq.adoption.session import session_name
from labhq.db.enums import AgentStatus, ApprovalStatus, RiskClass
from labhq.db.models import Agent, Project
from labhq.hierarchy import CEO, MANAGER, HierarchyError
from tests.adoption.conftest import World, adopt, wait_for


async def test_a_request_is_a_pending_light_approval_and_nothing_moves(world: World) -> None:
    original = await world.start_original()

    request = await world.adoptions.request(original.pid, project="site")

    approval = await world.approvals.get(request.approval.id)
    assert approval.type == ADOPT_AGENT
    assert approval.status is ApprovalStatus.PENDING
    assert approval.risk_class is RiskClass.LIGHT
    assert approval.payload["pid"] == original.pid
    assert approval.payload["cwd"] == str(world.repo)
    assert approval.payload["pane"] is not None
    assert is_alive(original.pid, original.started_at)
    assert not world.private.has_session(session_name(original.pid))
    assert [line.split()[0] for line in world.drivers] == ["start"]
    assert world.inbox == []
    async with world.sessions() as db:
        assert list(await db.scalars(select(Agent))) == []


async def test_the_confirmation_warns_when_no_sandbox_is_configured(world: World) -> None:
    original = await world.start_original()

    request = await world.adoptions.request(original.pid)

    assert request.warnings == (NO_ISOLATION_WARNING,)
    assert request.approval.payload["warnings"] == [NO_ISOLATION_WARNING]
    assert "do not prevent" in NO_ISOLATION_WARNING


async def test_the_move_waits_for_the_turn_then_continues_on_the_private_server(
    world: World,
) -> None:
    original, _ = await adopt(world, work=1.5)

    # The busy turn completed before the original process ended: it counted.
    assert (world.store / "turns").read_text(encoding="utf-8") == "1"
    starts = [line for line in world.drivers if line.startswith("start")]
    assert world.drivers[:2] == [f"start {original.pid} fresh", f"end {original.pid}"]
    assert len(starts) == 2 and starts[1].endswith(" continue")
    assert not any(line.startswith("CONFLICT") for line in world.drivers)
    assert not is_alive(original.pid, original.started_at)
    name = session_name(original.pid)
    assert world.private.has_session(name)
    screen = world.private.capture(name)
    assert f"continued=True turns=1 cwd={world.repo}" in screen
    # The owner's pane only ever received keys from the owner: nothing from labhq.
    first_message = world.inbox[0] if world.inbox else ""
    assert first_message.startswith("labhq: you are now this project's manager")


async def test_the_adopted_agent_manages_the_project_under_the_ceo(world: World) -> None:
    _, agent_id = await adopt(world)
    session = (world.store / "session").read_text(encoding="utf-8")

    async with world.sessions() as db:
        manager = await db.get_one(Agent, agent_id)
        ceo = await db.get_one(Agent, manager.reports_to)
        project = await db.get_one(Project, manager.project_id)

    assert manager.role == MANAGER
    assert manager.status is AgentStatus.ACTIVE
    assert ceo.role == CEO
    assert project.name == "site"
    assert Path(project.repo_path) == world.repo
    state = state_of(manager)
    assert state is not None
    assert state.session_id == session
    assert manager.config["agent"] == "fake-cli"


async def test_a_project_with_a_manager_cannot_adopt_another(world: World) -> None:
    await adopt(world)
    await wait_for(lambda: len(world.drivers) >= 3, "the continued agent")
    second = await world.start_original()

    with pytest.raises(HierarchyError, match="already has manager"):
        await world.adoptions.request(second.pid, project="site")
