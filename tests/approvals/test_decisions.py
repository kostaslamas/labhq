"""Every decision is recorded in full, and only a strong enough confirmation can approve."""

import pytest

from labhq.approvals import (
    ActionType,
    ApprovalNotFoundError,
    ApprovalNotPendingError,
    ConfirmationNotAllowedError,
    UnknownEntryError,
)
from labhq.db.enums import ApprovalStatus, RiskClass
from tests.approvals.conftest import World

PAYLOAD = {"members": ["developer", "qa"], "lead": "manager"}


@pytest.fixture
def voice() -> str:
    # Built in since Phase 2: light approvals only (plan §5, rule 7).
    return "voice"


@pytest.mark.parametrize("decision", ["approve", "reject"])
async def test_a_decision_records_payload_risk_class_decider_kind_and_time(
    world: World, decision: str
) -> None:
    requested = await world.service.request(
        "merge", PAYLOAD, task_id=world.task_id, agent_id=world.agent_id
    )
    world.clock.advance(90)

    decide = getattr(world.service, decision)
    await decide(requested.id, decider="operator", confirmation="cli", note="looks right")

    row = await world.service.get(requested.id)
    assert row.payload == PAYLOAD
    assert row.risk_class == RiskClass.HEAVY
    assert row.decided_by == "operator"
    assert row.confirmation_kind == "cli"
    assert row.decided_at == world.clock.now()
    assert row.decided_at.tzinfo is not None
    assert row.decision_note == "looks right"
    assert row.created_at < row.decided_at
    assert row.requested_by_agent_id == world.agent_id
    assert row.task_id == world.task_id


async def test_a_pending_approval_has_no_decision(world: World) -> None:
    requested = await world.service.request("merge", PAYLOAD)

    row = await world.service.get(requested.id)

    assert row.status == ApprovalStatus.PENDING
    assert (row.decided_by, row.decided_at, row.confirmation_kind) == (None, None, None)


async def test_a_light_only_confirmation_cannot_approve_a_heavy_action(
    world: World, voice: str
) -> None:
    requested = await world.service.request("merge", PAYLOAD)

    with pytest.raises(ConfirmationNotAllowedError):
        await world.service.approve(requested.id, decider="operator", confirmation=voice)

    row = await world.service.get(requested.id)
    assert row.status == ApprovalStatus.PENDING
    assert row.decided_by is None


async def test_a_light_only_confirmation_approves_a_light_action(world: World, voice: str) -> None:
    requested = await world.service.request("change_priority", {"task_id": world.task_id})

    approved = await world.service.approve(requested.id, decider="operator", confirmation=voice)

    assert approved.status == ApprovalStatus.APPROVED
    assert approved.confirmation_kind == voice


async def test_any_confirmation_may_reject(world: World, voice: str) -> None:
    requested = await world.service.request("merge", PAYLOAD)

    rejected = await world.service.reject(requested.id, decider="operator", confirmation=voice)

    assert rejected.status == ApprovalStatus.REJECTED


async def test_an_unknown_confirmation_kind_decides_nothing(world: World) -> None:
    requested = await world.service.request("merge", PAYLOAD)

    for decide in (world.service.approve, world.service.reject):
        with pytest.raises(UnknownEntryError):
            await decide(requested.id, decider="operator", confirmation="carrier-pigeon")

    assert (await world.service.get(requested.id)).status == ApprovalStatus.PENDING


async def test_a_decided_approval_cannot_be_decided_again(world: World) -> None:
    requested = await world.service.request("merge", PAYLOAD)
    await world.service.reject(requested.id, decider="operator", confirmation="cli")

    with pytest.raises(ApprovalNotPendingError, match="rejected"):
        await world.service.reject(requested.id, decider="someone else", confirmation="cli")

    assert (await world.service.get(requested.id)).decided_by == "operator"


async def test_deciding_a_missing_approval_fails(world: World) -> None:
    with pytest.raises(ApprovalNotFoundError):
        await world.service.approve(404, decider="operator", confirmation="cli")


async def test_list_filters_by_status_in_request_order(world: World) -> None:
    world.actions.register("note", ActionType("note", RiskClass.LIGHT))
    first = await world.service.request("note", {"n": 1})
    world.clock.advance(1)
    second = await world.service.request("note", {"n": 2})
    world.clock.advance(1)
    third = await world.service.request("note", {"n": 3})
    await world.service.reject(second.id, decider="operator", confirmation="cli")

    pending = await world.service.list(ApprovalStatus.PENDING)
    everything = await world.service.list()

    assert [a.id for a in pending] == [first.id, third.id]
    assert [a.id for a in everything] == [first.id, second.id, third.id]
