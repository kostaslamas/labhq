"""An outward-facing action is a heavy approval; nothing happens until a passkey approves it."""

import pytest

from labhq.approvals import ApprovalService, default_actions, default_confirmations
from labhq.approvals.policy import OUTWARD_ACTIONS
from labhq.approvals.service import ConfirmationNotAllowedError
from labhq.db.enums import ApprovalStatus, RiskClass
from labhq.db.models import Approval
from tests.departments.conftest import Research


def _service(research: Research) -> ApprovalService:
    return ApprovalService(
        research.org.sessions,
        clock=research.org.clock,
        actions=default_actions.copy(),
        executors=research.org.executors,
        confirmations=default_confirmations.copy(),
    )


async def _request(research: Research, action: str = "send_email") -> Approval:
    answer = await research.org.call(
        "request_outward_action",
        research.head,
        action=action,
        summary="Email the press list",
        details="To: press@example.com",
    )
    assert "Nothing happens until the owner approves it with a passkey" in answer
    (approval,) = await research.org.approvals()
    return approval


async def test_an_outward_action_waits_for_the_owner(research: Research) -> None:
    approval = await _request(research)
    assert (approval.type, approval.risk_class) == ("send_email", RiskClass.HEAVY)
    assert approval.status is ApprovalStatus.PENDING
    assert approval.payload["department"] == research.department
    assert approval.requested_by_agent_id == research.head
    assert approval.execution is None


@pytest.mark.parametrize("weak", ["voice", "tap", "ceo"])
async def test_only_a_strong_confirmation_approves_it(research: Research, weak: str) -> None:
    approval = await _request(research)
    with pytest.raises(ConfirmationNotAllowedError):
        await _service(research).approve(approval.id, decider="owner", confirmation=weak)
    assert (await research.org.get(Approval, approval.id)).status is ApprovalStatus.PENDING


async def test_a_passkey_approval_is_recorded_and_executes_nothing(research: Research) -> None:
    approval = await _request(research)
    decided = await _service(research).approve(approval.id, decider="owner", confirmation="passkey")
    # No executor is registered yet, so approval is as far as it goes.
    assert decided.status is ApprovalStatus.APPROVED
    assert decided.execution is None


@pytest.mark.parametrize("action", [action.key for action in OUTWARD_ACTIONS])
async def test_every_outward_type_is_heavy_and_has_no_executor(
    research: Research, action: str
) -> None:
    assert default_actions.get(action).risk_class is RiskClass.HEAVY
    assert action not in research.org.executors


async def test_an_unknown_action_is_refused(research: Research) -> None:
    answer = await research.org.call(
        "request_outward_action", research.head, action="merge", summary="x"
    )
    assert answer.startswith("Refused:")
    assert await research.org.approvals() == []
