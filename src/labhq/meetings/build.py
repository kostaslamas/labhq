"""Assemble a `MeetingService` with the runners it needs: rounds and the live decision room."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.approvals import ApprovalService
from labhq.clock import Clock
from labhq.meetings.events import MeetingListeners
from labhq.meetings.room import DecisionRoom
from labhq.meetings.runner import MeetingRunner
from labhq.meetings.service import MeetingService
from labhq.runs import RunService


def build_meeting_service(
    sessions: async_sessionmaker[AsyncSession],
    clock: Clock,
    approvals: ApprovalService,
    listeners: MeetingListeners,
) -> MeetingService:
    # Turns run each agent through its own adapter, outside any task checkout.
    runs = RunService(sessions, clock=clock)
    runner = MeetingRunner(sessions, clock=clock, runs=runs, listeners=listeners)
    room = DecisionRoom(sessions, clock=clock, runs=runs, approvals=approvals, listeners=listeners)
    return MeetingService(sessions, clock=clock, approvals=approvals, runner=runner, room=room)
