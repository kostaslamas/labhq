"""Run a started meeting: rounds of turns, then the facilitator's minutes.

Each turn is a run through `labhq.runs`, so its cost lands in `cost_events` under the
project. The budget is checked before every run; at the stop threshold no further run
starts and the meeting ends with what it has. Every run, answered or not, leaves a
transcript entry with its run id, which is how the meeting's cost is found.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.approvals.registry import Registry
from labhq.budgets import BudgetSettings, Decision, check
from labhq.clock import Clock
from labhq.db.enums import MeetingStatus, RunStatus, TranscriptSource
from labhq.db.models import Agent, Meeting, MeetingParticipant, Project
from labhq.meetings.events import MeetingEvent, MeetingEventKind, MeetingListeners
from labhq.meetings.events import default_listeners as builtin_listeners
from labhq.meetings.kinds import MeetingKind
from labhq.meetings.kinds import default_kinds as builtin_kinds
from labhq.meetings.prompts import Seat, minutes_prompt, turn_prompt
from labhq.meetings.record import record_minutes
from labhq.meetings.reply import InvalidMinutesError, MinutesReply, parse_minutes
from labhq.meetings.settings import MeetingSettings, get_meeting_settings
from labhq.meetings.transcript import add_entry, lines
from labhq.runs import RunService, RunStartError

logger = logging.getLogger(__name__)

BUDGET_REASON = "budget"
INVALID_MINUTES_REASON = "invalid_minutes"
UNRECORDED_MINUTES_REASON = "minutes_not_recorded"

# What the transcript says when a meeting stops early, by end reason.
_END_NOTES = {
    BUDGET_REASON: "Meeting ended early: the budget stop was reached.",
    INVALID_MINUTES_REASON: "Meeting failed: the minutes were not valid JSON.",
    UNRECORDED_MINUTES_REASON: "Meeting failed: the minutes could not be recorded.",
}


class MeetingNotStartableError(RuntimeError):
    pass


@dataclass(frozen=True)
class Context:
    meeting_id: int
    kind: MeetingKind
    project: str
    agenda: str
    seats: Sequence[Seat]
    facilitator: Seat


class MeetingRunner:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        clock: Clock,
        runs: RunService,
        kinds: Registry[MeetingKind] = builtin_kinds,
        listeners: MeetingListeners = builtin_listeners,
        settings: MeetingSettings | None = None,
        budget_settings: BudgetSettings | None = None,
    ) -> None:
        self._sessions = sessions
        self._clock = clock
        self._runs = runs
        self._kinds = kinds
        self._listeners = listeners
        self._settings = settings or get_meeting_settings()
        self._budget_settings = budget_settings

    async def run(self, meeting_id: int) -> Meeting:
        """Take a requested meeting to `ended` or `failed`."""
        context = await self._begin(meeting_id)
        await self._emit(MeetingEventKind.STARTED, meeting_id)
        for round_number in range(1, context.kind.rounds + 1):
            for seat in context.seats:
                if not await self._may_start(seat.agent_id):
                    return await self._end(meeting_id, MeetingStatus.ENDED, BUDGET_REASON)
                await self._turn(context, seat, round_number)
        return await self._minutes(context)

    async def _begin(self, meeting_id: int) -> Context:
        async with self._sessions() as db:
            meeting = await db.get_one(Meeting, meeting_id)
            kind = self._kinds.get(meeting.kind)
            project = await db.get_one(Project, meeting.project_id)
            seats = await _seats(db, meeting_id)
            if not seats:
                raise MeetingNotStartableError(f"meeting {meeting_id} has no agent participants")
            # Conditional, so two starters racing on one meeting cannot both run it.
            claimed = await db.execute(
                update(Meeting)
                .where(Meeting.id == meeting_id, Meeting.status == MeetingStatus.REQUESTED)
                .values(status=MeetingStatus.RUNNING, started_at=self._clock.now())
            )
            if claimed.rowcount != 1:  # type: ignore[attr-defined]
                raise MeetingNotStartableError(f"meeting {meeting_id} is not waiting to start")
            await db.commit()
        facilitator = next(
            (seat for seat in seats if seat.agent_id == meeting.facilitator_agent_id), seats[0]
        )
        return Context(
            meeting_id=meeting_id,
            kind=kind,
            project=project.name,
            agenda=meeting.agenda,
            seats=seats,
            facilitator=facilitator,
        )

    async def _may_start(self, agent_id: int) -> bool:
        async with self._sessions() as db:
            budget = await check(db, agent_id, self._clock, self._budget_settings)
            # The check records the once-per-period warning; keep it.
            await db.commit()
        return budget.decision is not Decision.STOP

    async def _turn(self, context: Context, seat: Seat, round_number: int) -> None:
        async with self._sessions() as db:
            transcript = await lines(db, context.meeting_id)
        prompt = turn_prompt(
            kind=context.kind,
            project=context.project,
            agenda=context.agenda,
            seat=seat,
            round_number=round_number,
            transcript=transcript,
        )
        text, run_id = await self._ask(seat.agent_id, prompt)
        await self._say(context.meeting_id, seat, text, run_id)

    async def _minutes(self, context: Context) -> Meeting:
        assignees = {seat.agent_id for seat in context.seats}
        error: str | None = None
        for _attempt in range(self._settings.minutes_attempts):
            if not await self._may_start(context.facilitator.agent_id):
                return await self._end(context.meeting_id, MeetingStatus.ENDED, BUDGET_REASON)
            async with self._sessions() as db:
                transcript = await lines(db, context.meeting_id)
            prompt = minutes_prompt(
                kind=context.kind,
                project=context.project,
                agenda=context.agenda,
                seats=context.seats,
                transcript=transcript,
                previous_error=error,
            )
            text, run_id = await self._ask(context.facilitator.agent_id, prompt)
            await self._say(context.meeting_id, context.facilitator, text, run_id)
            try:
                minutes = parse_minutes(text, assignees)
            except InvalidMinutesError as invalid:
                error = str(invalid)
                continue
            return await self._close(context.meeting_id, minutes)
        return await self._end(context.meeting_id, MeetingStatus.FAILED, INVALID_MINUTES_REASON)

    async def _ask(self, agent_id: int, prompt: str) -> tuple[str | None, int]:
        try:
            active = await self._runs.start(agent_id=agent_id, task_id=None, prompt=prompt)
        except RunStartError as error:
            return None, error.run_id
        run = await active.wait()
        if run.status is not RunStatus.SUCCEEDED or active.result is None:
            return None, run.id
        return active.result.text, run.id

    async def _say(self, meeting_id: int, seat: Seat, text: str | None, run_id: int) -> None:
        async with self._sessions() as db:
            if text:
                participant_id = await db.scalar(
                    select(MeetingParticipant.id).where(
                        MeetingParticipant.meeting_id == meeting_id,
                        MeetingParticipant.agent_id == seat.agent_id,
                    )
                )
                entry = await add_entry(
                    db,
                    self._clock,
                    meeting_id=meeting_id,
                    source=TranscriptSource.AGENT,
                    text=text,
                    participant_id=participant_id,
                    run_id=run_id,
                )
            else:
                entry = await add_entry(
                    db,
                    self._clock,
                    meeting_id=meeting_id,
                    source=TranscriptSource.SYSTEM,
                    text=f"{seat.name} did not reply (run #{run_id}).",
                    run_id=run_id,
                )
            await db.commit()
        await self._emit(MeetingEventKind.ENTRY_ADDED, meeting_id, entry.id)

    async def _close(self, meeting_id: int, minutes: MinutesReply) -> Meeting:
        async with self._sessions() as db:
            meeting = await db.get_one(Meeting, meeting_id)
            try:
                await record_minutes(db, self._clock, meeting, minutes)
                meeting.status = MeetingStatus.ENDED
                meeting.ended_at = self._clock.now()
                await db.commit()
            except Exception:
                logger.exception("the minutes of meeting %s were not recorded", meeting_id)
                await db.rollback()
            else:
                await self._emit(MeetingEventKind.ENDED, meeting_id)
                return meeting
        return await self._end(meeting_id, MeetingStatus.FAILED, UNRECORDED_MINUTES_REASON)

    async def _end(self, meeting_id: int, status: MeetingStatus, reason: str) -> Meeting:
        async with self._sessions() as db:
            entry = await add_entry(
                db,
                self._clock,
                meeting_id=meeting_id,
                source=TranscriptSource.SYSTEM,
                text=_END_NOTES[reason],
            )
            meeting = await db.get_one(Meeting, meeting_id)
            meeting.status = status
            meeting.end_reason = reason
            meeting.ended_at = self._clock.now()
            await db.commit()
        await self._emit(MeetingEventKind.ENTRY_ADDED, meeting_id, entry.id)
        await self._emit(MeetingEventKind.ENDED, meeting_id)
        return meeting

    async def _emit(
        self, kind: MeetingEventKind, meeting_id: int, entry_id: int | None = None
    ) -> None:
        await self._listeners.emit(MeetingEvent(kind, meeting_id, entry_id))


async def _seats(db: AsyncSession, meeting_id: int) -> list[Seat]:
    rows = await db.execute(
        select(MeetingParticipant.display_name, Agent.id, Agent.role)
        .join(Agent, MeetingParticipant.agent_id == Agent.id)
        .where(MeetingParticipant.meeting_id == meeting_id)
        .order_by(MeetingParticipant.id)
    )
    return [Seat(agent_id=agent_id, name=name, role=role) for name, agent_id, role in rows]
