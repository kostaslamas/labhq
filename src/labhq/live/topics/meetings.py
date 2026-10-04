"""The `meetings` topic: a transcript entry, a decision, an action item or a status change.

Entries are written by the meeting runner or by `labhq` in another process; the watermark
reads SQLite, so the page sees all of them.
"""

from sqlalchemy import func, select

from labhq.db.enums import MeetingStatus
from labhq.db.models import Meeting, MeetingActionItem, MeetingDecision, MeetingTranscriptEntry
from labhq.live.registry import aggregates, default_topics, status_counts

default_topics.register(
    "meetings",
    aggregates(
        func.max(Meeting.id),
        func.count(Meeting.id),
        *status_counts(Meeting.status, MeetingStatus),
        # Scalar subqueries keep the four tables from multiplying into one cross join.
        select(func.max(MeetingTranscriptEntry.id)).scalar_subquery(),
        select(func.count(MeetingTranscriptEntry.id)).scalar_subquery(),
        select(func.count(MeetingDecision.id)).scalar_subquery(),
        select(func.count(MeetingActionItem.id)).scalar_subquery(),
    ),
)
