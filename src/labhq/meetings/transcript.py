"""Transcript entries: what agents, the owner and the engine said, in order.

Owner entries arrive from any source (CLI, chat thread, UI) through `add_owner_entry`. An
entry mirrored from a chat thread carries its `external_ref`, and the unique
`(meeting_id, external_ref)` records it once however often it arrives.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.clock import Clock
from labhq.db.enums import MeetingStatus, TranscriptSource
from labhq.db.models import Meeting, MeetingParticipant, MeetingTranscriptEntry
from labhq.meetings.events import MeetingEvent, MeetingEventKind, MeetingListeners
from labhq.meetings.events import default_listeners as builtin_listeners
from labhq.meetings.settings import get_meeting_settings

# An owner may still write while the meeting waits for approval or runs; after that the
# transcript is closed.
OPEN_STATUSES = frozenset({MeetingStatus.REQUESTED, MeetingStatus.RUNNING})


class MeetingClosedError(RuntimeError):
    pass


@dataclass(frozen=True)
class Line:
    """One transcript entry as a prompt shows it."""

    speaker: str
    text: str


async def add_entry(
    db: AsyncSession,
    clock: Clock,
    *,
    meeting_id: int,
    source: TranscriptSource,
    text: str,
    participant_id: int | None = None,
    run_id: int | None = None,
) -> MeetingTranscriptEntry:
    entry = MeetingTranscriptEntry(
        meeting_id=meeting_id,
        participant_id=participant_id,
        source=source,
        text=text,
        run_id=run_id,
        created_at=clock.now(),
    )
    db.add(entry)
    await db.flush()
    return entry


async def add_owner_entry(
    sessions: async_sessionmaker[AsyncSession],
    clock: Clock,
    *,
    meeting_id: int,
    text: str,
    external_ref: str | None = None,
    display_name: str | None = None,
    listeners: MeetingListeners = builtin_listeners,
) -> MeetingTranscriptEntry | None:
    """Record what the owner said. Returns None when `external_ref` was already recorded."""
    async with sessions() as db:
        meeting = await db.get_one(Meeting, meeting_id)
        if meeting.status not in OPEN_STATUSES:
            raise MeetingClosedError(f"meeting {meeting_id} is {meeting.status}")
        participant = await _owner(db, meeting_id, display_name)
        statement = (
            insert(MeetingTranscriptEntry)
            .values(
                meeting_id=meeting_id,
                participant_id=participant.id,
                source=TranscriptSource.OWNER,
                text=text,
                external_ref=external_ref,
                created_at=clock.now(),
            )
            .on_conflict_do_nothing(index_elements=["meeting_id", "external_ref"])
            .returning(MeetingTranscriptEntry.id)
        )
        entry_id = await db.scalar(statement)
        await db.commit()
        if entry_id is None:
            return None
        entry = await db.get_one(MeetingTranscriptEntry, entry_id)
    await listeners.emit(MeetingEvent(MeetingEventKind.ENTRY_ADDED, meeting_id, entry_id))
    return entry


async def lines(db: AsyncSession, meeting_id: int) -> list[Line]:
    """The transcript in order, each entry with its speaker's name."""
    rows = await db.execute(
        select(MeetingTranscriptEntry, MeetingParticipant.display_name)
        .outerjoin(
            MeetingParticipant, MeetingTranscriptEntry.participant_id == MeetingParticipant.id
        )
        .where(MeetingTranscriptEntry.meeting_id == meeting_id)
        .order_by(MeetingTranscriptEntry.id)
    )
    return [Line(name or entry.source.value, entry.text) for entry, name in rows]


async def _owner(db: AsyncSession, meeting_id: int, display_name: str | None) -> MeetingParticipant:
    participant = await db.scalar(
        select(MeetingParticipant).where(
            MeetingParticipant.meeting_id == meeting_id, MeetingParticipant.agent_id.is_(None)
        )
    )
    if participant is not None:
        return participant
    participant = MeetingParticipant(
        meeting_id=meeting_id,
        agent_id=None,
        display_name=display_name or get_meeting_settings().owner_name,
    )
    db.add(participant)
    await db.flush()
    return participant
