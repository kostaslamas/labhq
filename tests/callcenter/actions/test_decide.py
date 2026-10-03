import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.approvals import default_confirmations
from labhq.callcenter.actions import decide
from labhq.clock import FakeClock
from labhq.db.enums import ApprovalStatus, RiskClass
from labhq.db.models import Approval
from labhq.speech import speakable


async def _approval(session: AsyncSession, clock: FakeClock, kind: str, risk: RiskClass) -> int:
    row = Approval(type=kind, risk_class=risk, payload={}, created_at=clock.now())
    session.add(row)
    await session.commit()
    return row.id


async def _reload(session: AsyncSession, approval_id: int) -> Approval:
    session.expire_all()
    return await session.get_one(Approval, approval_id)


def test_voice_confirmation_is_light_only() -> None:
    voice = default_confirmations.get("voice")
    assert voice.can_approve(RiskClass.LIGHT)
    assert not voice.can_approve(RiskClass.HEAVY)


async def test_heavy_approval_is_requested_not_resolved(
    session: AsyncSession, clock: FakeClock
) -> None:
    approval_id = await _approval(session, clock, "push", RiskClass.HEAVY)

    answer = await decide(session, clock, f"A{approval_id}", "approve")

    assert "approval requested" in answer.lower()
    assert "passkey" in answer
    row = await _reload(session, approval_id)
    assert row.status == ApprovalStatus.PENDING
    assert row.decided_by is None
    assert row.execution is None
    assert speakable(answer) == answer


async def test_light_approval_is_resolved_with_the_voice_audit(
    session: AsyncSession, clock: FakeClock
) -> None:
    approval_id = await _approval(session, clock, "assign_task", RiskClass.LIGHT)

    answer = await decide(session, clock, f"a {approval_id}", "Approve")

    row = await _reload(session, approval_id)
    assert row.status == ApprovalStatus.APPROVED
    assert row.decided_by == "call_center"
    assert row.confirmation_kind == "voice"
    assert row.decided_at == clock.now()
    assert speakable(answer) == answer


async def test_rejecting_by_voice_works_even_for_a_heavy_approval(
    session: AsyncSession, clock: FakeClock
) -> None:
    approval_id = await _approval(session, clock, "merge", RiskClass.HEAVY)

    answer = await decide(session, clock, f"A{approval_id}", "reject")

    row = await _reload(session, approval_id)
    assert row.status == ApprovalStatus.REJECTED
    assert (row.decided_by, row.confirmation_kind) == ("call_center", "voice")
    assert speakable(answer) == answer


@pytest.mark.parametrize(
    ("reference", "verdict", "expected"),
    [
        ("A999", "approve", "no approval A999"),
        ("twelve", "approve", "did not catch"),
        ("A1", "maybe", "approve or reject"),
    ],
)
async def test_unusable_requests_get_a_speakable_explanation(
    session: AsyncSession, clock: FakeClock, reference: str, verdict: str, expected: str
) -> None:
    answer = await decide(session, clock, reference, verdict)

    assert expected in answer
    assert speakable(answer) == answer


async def test_deciding_twice_reports_the_state(session: AsyncSession, clock: FakeClock) -> None:
    approval_id = await _approval(session, clock, "assign_task", RiskClass.LIGHT)
    await decide(session, clock, f"A{approval_id}", "approve")

    answer = await decide(session, clock, f"A{approval_id}", "reject")

    assert "already approved" in answer
    assert (await _reload(session, approval_id)).status == ApprovalStatus.APPROVED
