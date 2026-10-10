"""The CEO starts a meeting: request it, decide its light approval, run it in the background."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.approvals import ApprovalService
from labhq.ceoorg.background import spawn
from labhq.ceoorg.record import actor
from labhq.clock import Clock
from labhq.db.models import Meeting
from labhq.meetings import MeetingError, MeetingListeners, MeetingService
from labhq.meetings.build import build_meeting_service
from labhq.meetings.channels.meeting_posts import MeetingMirror
from labhq.meetings.proposal import default_proposals
from labhq.work import find_project

CEO_CONFIRMATION = "ceo"


def meeting_service(
    sessions: async_sessionmaker[AsyncSession], clock: Clock, approvals: ApprovalService
) -> MeetingService:
    # Mirrored to chat like every meeting; turns run each agent through its own adapter.
    listeners = MeetingListeners()
    MeetingMirror(sessions, clock).install(listeners)
    return build_meeting_service(sessions, clock, approvals, listeners)


async def start_meeting(
    service: MeetingService,
    approvals: ApprovalService,
    sessions: async_sessionmaker[AsyncSession],
    *,
    caller: int,
    project: str,
    kind: str,
) -> Meeting:
    async with sessions() as db:
        project_id = (await find_project(db, project)).id
    if service.kind(kind).owner_starts:
        raise MeetingError(
            f"A {kind} meeting starts only when the owner approves it: use propose_decision_room."
        )
    meeting = await service.request(project_id=project_id, kind=kind, requested_by=caller)
    assert meeting.approval_id is not None
    await approvals.approve(
        meeting.approval_id, decider=actor(caller), confirmation=CEO_CONFIRMATION
    )
    spawn(service.start(meeting.id), name=f"meeting-{meeting.id}")
    return meeting


async def propose_room(
    service: MeetingService,
    sessions: async_sessionmaker[AsyncSession],
    *,
    caller: int,
    project: str,
    topic: str | None,
    proposal: tuple[str, int] | None,
) -> Meeting:
    """Request a decision room. The CEO cannot approve it: the owner sees the cost and decides."""
    async with sessions() as db:
        project_id = (await find_project(db, project)).id
        if proposal is not None:
            described = await default_proposals.get(proposal[0])(db, proposal[1])
            if described is None:
                raise MeetingError(f"there is no {proposal[0]} {proposal[1]} to discuss")
    return await service.request(
        project_id=project_id, kind="decision", agenda=topic, requested_by=caller, pinned=proposal
    )
