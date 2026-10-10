"""Meetings: standup, planning and review with transcript, decisions and action items.

Kinds and event listeners are registries: a new kind or a new mirror is a registration.
"""

from labhq.meetings.actions import DECISION_ACTION
from labhq.meetings.cost import meeting_cost_micros
from labhq.meetings.events import (
    Listener,
    MeetingEvent,
    MeetingEventKind,
    MeetingListeners,
    default_listeners,
)
from labhq.meetings.kinds import MeetingKind, default_kinds
from labhq.meetings.minutes import MeetingNotFoundError, MinutesView, read_minutes
from labhq.meetings.reply import InvalidMinutesError, MinutesReply, parse_minutes
from labhq.meetings.room import DecisionRoom, RoomClosedError
from labhq.meetings.runner import MeetingNotStartableError, MeetingRunner
from labhq.meetings.service import (
    START_MEETING_ACTION,
    MeetingError,
    MeetingNotApprovedError,
    MeetingService,
)
from labhq.meetings.settings import MeetingSettings, get_meeting_settings
from labhq.meetings.transcript import MeetingClosedError, add_owner_entry

__all__ = [
    "DECISION_ACTION",
    "START_MEETING_ACTION",
    "DecisionRoom",
    "InvalidMinutesError",
    "Listener",
    "MeetingClosedError",
    "MeetingError",
    "MeetingEvent",
    "MeetingEventKind",
    "MeetingKind",
    "MeetingListeners",
    "MeetingNotApprovedError",
    "MeetingNotFoundError",
    "MeetingNotStartableError",
    "MeetingRunner",
    "MeetingService",
    "MeetingSettings",
    "MinutesReply",
    "MinutesView",
    "RoomClosedError",
    "add_owner_entry",
    "default_kinds",
    "default_listeners",
    "get_meeting_settings",
    "meeting_cost_micros",
    "parse_minutes",
    "read_minutes",
]
