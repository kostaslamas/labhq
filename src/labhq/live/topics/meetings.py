"""The `meetings` topic: a transcript entry, a decision, an action item or a status change.

Entries are written by the meeting runner or by `labhq` in another process; the watermark
reads SQLite, so the page sees all of them.
"""

from sqlalchemy import func, select

from labhq.db.enums import MeetingStatus
from labhq.db.models import (
    CostEvent,
    Meeting,
    MeetingActionItem,
    MeetingDecision,
    MeetingTranscriptEntry,
)
from labhq.live.registry import aggregates, default_topics, status_counts

default_topics.register(
    "meetings",
    aggregates(
        func.max(Meeting.id),
        func.count(Meeting.id),
        # A live room waiting for an agent changes what the widget shows, with no new entry.
        func.count(Meeting.waiting_agent_id),
        *status_counts(Meeting.status, MeetingStatus),
        # Scalar subqueries keep the four tables from multiplying into one cross join.
        select(func.max(MeetingTranscriptEntry.id)).scalar_subquery(),
        select(func.count(MeetingTranscriptEntry.id)).scalar_subquery(),
        select(func.count(MeetingDecision.id)).scalar_subquery(),
        select(func.count(MeetingActionItem.id)).scalar_subquery(),
        # The running total of a room moves when a run's cost lands, before its entry does.
        select(func.max(CostEvent.id)).scalar_subquery(),
    ),
)
