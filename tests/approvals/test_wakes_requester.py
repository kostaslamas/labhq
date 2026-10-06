"""An agent that asked for an approval is woken once when the owner decides it."""

import pytest
from sqlalchemy import select

from labhq.approvals import ApprovalNotPendingError
from labhq.db.enums import WakeupSource
from labhq.db.models import WakeupRequest
from tests.approvals.conftest import World

PAYLOAD = {"members": ["developer"], "lead": "manager"}


async def _resolved_wakeups(world: World) -> list[WakeupRequest]:
    async with world.sessions() as db:
        return list(
            await db.scalars(
                select(WakeupRequest).where(WakeupRequest.source == WakeupSource.APPROVAL_RESOLVED)
            )
        )


@pytest.mark.parametrize("decision", ["approve", "reject"])
async def test_deciding_wakes_the_requester_once(world: World, decision: str) -> None:
    requested = await world.service.request("delete_branch", PAYLOAD, agent_id=world.agent_id)

    await getattr(world.service, decision)(requested.id, decider="owner", confirmation="cli")
    with pytest.raises(ApprovalNotPendingError):
        await getattr(world.service, decision)(requested.id, decider="owner", confirmation="cli")

    (wakeup,) = await _resolved_wakeups(world)
    assert wakeup.agent_id == world.agent_id
    assert f"A{requested.id}" in wakeup.reason
    assert ("approved" if decision == "approve" else "rejected") in wakeup.reason


async def test_an_approval_nobody_requested_wakes_no_one(world: World) -> None:
    requested = await world.service.request("delete_branch", PAYLOAD)

    await world.service.approve(requested.id, decider="owner", confirmation="cli")

    assert await _resolved_wakeups(world) == []
