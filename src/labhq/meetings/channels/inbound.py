"""The owner's replies in a meeting thread, recorded as owner entries of that meeting.

The reply's message ref becomes the entry's `external_ref`, and the transcript's unique
`(meeting_id, external_ref)` records it once however often the service delivers it.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.chat import Reply
from labhq.clock import Clock
from labhq.db.models import Meeting, MeetingTranscriptEntry
from labhq.meetings.events import MeetingListeners
from labhq.meetings.events import default_listeners as builtin_listeners
from labhq.meetings.transcript import MeetingClosedError, add_owner_entry

logger = logging.getLogger(__name__)


async def receive(
    sessions: async_sessionmaker[AsyncSession],
    clock: Clock,
    adapter: str,
    reply: Reply,
    *,
    listeners: MeetingListeners = builtin_listeners,
) -> MeetingTranscriptEntry | None:
    """Record `reply` in its meeting; None when it is a repeat, closed, or not a meeting's."""
    async with sessions() as db:
        meeting_id = await db.scalar(
            select(Meeting.id).where(
                Meeting.channel_adapter == adapter, Meeting.external_ref == reply.thread.id
            )
        )
    if meeting_id is None:
        # An incident thread, or a thread of another adapter: nothing to record.
        return None
    try:
        return await add_owner_entry(
            sessions,
            clock,
            meeting_id=meeting_id,
            text=reply.text,
            external_ref=reply.ref,
            listeners=listeners,
        )
    except MeetingClosedError:
        logger.info("reply %s came after meeting %s closed; not recorded", reply.ref, meeting_id)
        return None
