"""What a meeting owes its thread: the agenda when it starts, each entry, then the minutes.

`MeetingMirror.install` registers its listener in the meeting event registry of whoever runs
the meeting (`labhq meetings start`). It only writes outbox rows, so it never waits on a chat
service: the meeting runs at database speed whether the adapter is up, down or not
configured (plan §2.1).
"""

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.chat import Persona
from labhq.clock import Clock
from labhq.db.models import Agent, Meeting, MeetingParticipant, MeetingTranscriptEntry, Project
from labhq.meetings.channels.outbox import Destination, enqueue
from labhq.meetings.channels.personas import agent_persona, system_persona
from labhq.meetings.channels.settings import ChannelSettings, get_channel_settings
from labhq.meetings.events import MeetingEvent, MeetingEventKind, MeetingListeners
from labhq.meetings.minutes import MinutesView, read_minutes

LISTENER_NAME = "chat_channels"

type Render = Callable[[AsyncSession, Meeting, MeetingEvent], Awaitable[None]]


def project_channel_key(project_id: int) -> str:
    return f"project-{project_id}"


def meeting_thread_key(meeting_id: int) -> str:
    return f"meeting:{meeting_id}"


class MeetingMirror:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        clock: Clock,
        settings: ChannelSettings | None = None,
    ) -> None:
        self._sessions = sessions
        self._clock = clock
        self._settings = settings or get_channel_settings()
        # Dispatch is data: a new event kind is a new row.
        self._renderers: dict[MeetingEventKind, Render] = {
            MeetingEventKind.STARTED: self._agenda,
            MeetingEventKind.ENTRY_ADDED: self._entry,
            MeetingEventKind.ENDED: self._minutes,
        }

    def install(self, listeners: MeetingListeners) -> None:
        listeners.register(LISTENER_NAME, self.listener, replace=True)

    async def listener(self, event: MeetingEvent) -> None:
        render = self._renderers.get(event.kind)
        if render is None:
            return
        async with self._sessions() as db:
            meeting = await db.get_one(Meeting, event.meeting_id)
            await render(db, meeting, event)
            await db.commit()

    async def _agenda(self, db: AsyncSession, meeting: Meeting, _event: MeetingEvent) -> None:
        await self._enqueue(
            db,
            meeting,
            key=f"meeting:{meeting.id}:agenda",
            kind="agenda",
            persona=system_persona(self._settings),
            text=meeting.agenda,
        )

    async def _entry(self, db: AsyncSession, meeting: Meeting, event: MeetingEvent) -> None:
        if event.entry_id is None:
            return
        entry = await db.get_one(MeetingTranscriptEntry, event.entry_id)
        # An entry with a ref came from the chat thread itself; echoing it would say it twice.
        if entry.external_ref is not None:
            return
        await self._enqueue(
            db,
            meeting,
            key=f"meeting:{meeting.id}:entry:{entry.id}",
            kind="entry",
            persona=await self._speaker(db, entry),
            text=entry.text,
        )

    async def _minutes(self, db: AsyncSession, meeting: Meeting, _event: MeetingEvent) -> None:
        view = await read_minutes(db, meeting.id)
        facilitator = (
            await db.get(Agent, meeting.facilitator_agent_id)
            if meeting.facilitator_agent_id is not None
            else None
        )
        persona = (
            agent_persona(facilitator, self._settings)
            if facilitator is not None
            else system_persona(self._settings)
        )
        await self._enqueue(
            db,
            meeting,
            key=f"meeting:{meeting.id}:minutes",
            kind="minutes",
            persona=persona,
            text=render_minutes(view),
        )

    async def _speaker(self, db: AsyncSession, entry: MeetingTranscriptEntry) -> Persona:
        if entry.participant_id is None:
            return system_persona(self._settings)
        participant = await db.get_one(MeetingParticipant, entry.participant_id)
        if participant.agent_id is None:
            return Persona(participant.display_name)
        return agent_persona(await db.get_one(Agent, participant.agent_id), self._settings)

    async def _enqueue(
        self,
        db: AsyncSession,
        meeting: Meeting,
        *,
        key: str,
        kind: str,
        persona: Persona,
        text: str,
    ) -> None:
        project = await db.get_one(Project, meeting.project_id)
        destination = Destination(
            channel_key=project_channel_key(project.id),
            channel_name=project.name,
            thread_key=meeting_thread_key(meeting.id),
            thread_title=f"{meeting.kind.capitalize()} M{meeting.id}, "
            f"{meeting.created_at:%Y-%m-%d}",
        )
        await enqueue(
            db,
            key=key,
            kind=kind,
            destination=destination,
            persona=persona,
            text=text,
            now=self._clock.now(),
            meeting_id=meeting.id,
        )


def render_minutes(view: MinutesView) -> str:
    names: dict[int | None, str] = {
        p.agent_id: p.display_name for p in view.participants if p.agent_id is not None
    }
    outcome = f"{view.status}" + (f" ({view.end_reason})" if view.end_reason else "")
    lines = [f"Minutes of {view.kind} M{view.meeting_id}: {outcome}.", "", "Decisions:"]
    lines += [f"{d.position}. {d.text}" for d in view.decisions] or ["(none)"]
    lines += ["", "Action items:"]
    lines += [
        f"- {item.text} -> {names.get(item.assignee_agent_id, 'unassigned')} (task #{item.task_id})"
        for item in view.action_items
    ] or ["(none)"]
    return "\n".join(lines)
