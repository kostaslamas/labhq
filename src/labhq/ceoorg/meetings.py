"""The CEO starts a meeting: request it, decide its light approval, run it in the background."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.approvals import ApprovalService
from labhq.ceoorg.background import spawn
from labhq.ceoorg.record import actor
from labhq.clock import Clock
from labhq.db.models import Meeting
from labhq.meetings import MeetingListeners, MeetingRunner, MeetingService
from labhq.meetings.channels.meeting_posts import MeetingMirror
from labhq.runs import RunService
from labhq.work import find_project

CEO_CONFIRMATION = "ceo"


def meeting_service(
    sessions: async_sessionmaker[AsyncSession], clock: Clock, approvals: ApprovalService
) -> MeetingService:
    # Mirrored to chat like every meeting; turns run each agent through its own adapter.
    listeners = MeetingListeners()
    MeetingMirror(sessions, clock).install(listeners)
    runner = MeetingRunner(
        sessions, clock=clock, runs=RunService(sessions, clock=clock), listeners=listeners
    )
    return MeetingService(sessions, clock=clock, approvals=approvals, runner=runner)


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
    meeting = await service.request(project_id=project_id, kind=kind, requested_by=caller)
    assert meeting.approval_id is not None
    await approvals.approve(
        meeting.approval_id, decider=actor(caller), confirmation=CEO_CONFIRMATION
    )
    spawn(service.start(meeting.id), name=f"meeting-{meeting.id}")
    return meeting
