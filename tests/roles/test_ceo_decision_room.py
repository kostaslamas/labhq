"""The CEO may propose a decision room; only the owner can start it (issue #199)."""

from sqlalchemy import select

from labhq.db.enums import ApprovalStatus, MeetingStatus
from labhq.db.models import Approval, CeoReport, Meeting
from tests.roles.conftest import Org
from tests.roles.test_ceo_org_actions import ceo_actions, start_ceo_run


async def test_the_ceo_proposes_a_room_and_the_owner_alone_can_approve_it(org: Org) -> None:
    await start_ceo_run(org)
    async with org.sessions() as db:
        report = CeoReport(
            agent_id=org.ceo, text="Add a staging host.", refs=[], created_at=org.clock.now()
        )
        db.add(report)
        await db.commit()
        report_id = report.id

    answer = await org.call(
        "propose_decision_room",
        org.ceo,
        project="site",
        topic="Staging host?",
        proposal_kind="report",
        proposal_id=report_id,
    )

    [meeting] = await org.all(Meeting)
    approval = await org.get(Approval, meeting.approval_id or 0)
    assert (meeting.kind, meeting.status) == ("decision", MeetingStatus.REQUESTED)
    assert (meeting.pinned_kind, meeting.pinned_id) == ("report", report_id)
    assert (
        meeting.estimate_micros and approval.payload["estimate_micros"] == meeting.estimate_micros
    )
    # Pending: the CEO decided nothing.
    assert (approval.status, approval.decided_by) == (ApprovalStatus.PENDING, None)
    assert "owner approves" in answer
    assert ("propose_decision_room", f"agent:{org.ceo}") in await ceo_actions(org)


async def test_the_ceo_cannot_start_a_decision_room_itself(org: Org) -> None:
    await start_ceo_run(org)

    answer = await org.call("start_meeting", org.ceo, project="site", kind="decision")

    assert answer.startswith("Refused:") and "propose_decision_room" in answer
    assert await org.all(Meeting) == []


async def test_a_proposal_that_does_not_exist_is_refused(org: Org) -> None:
    await start_ceo_run(org)

    answer = await org.call(
        "propose_decision_room", org.ceo, project="site", proposal_kind="report", proposal_id=99
    )

    assert answer.startswith("Refused:")
    assert await org.all(Meeting) == []
    async with org.sessions() as db:
        assert list(await db.scalars(select(Approval))) == []
