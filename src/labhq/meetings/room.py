"""A live decision room: the owner, the CEO and a project's manager in one thread.

Unlike a round-based meeting, nobody holds a fixed turn. The room starts when the owner
approves it; the CEO opens, and each agent answers once after every owner message, in seat
order. `advance` runs whoever has not yet answered the owner's latest message and stops when
everyone has, so a new owner entry (or the start) is what moves the room on.

An agent that is a tmux session answers after it finishes its current step; the room records
that it is waiting and why. Two caps bound the cost: the agent-turn cap, and the hard USD cap
the owner approved the room under (issue #202). At either the room writes its minutes and ends.
Passing the high end of the estimate is announced once. Minutes record decisions; each action
item waits for the owner's approval (`labhq.meetings.actions`), so nothing executes on the
room's own authority.
"""

import asyncio
import logging
import weakref
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.adoption.state import state_of
from labhq.approvals import ApprovalService
from labhq.approvals.registry import Registry
from labhq.budgets import BudgetSettings
from labhq.clock import Clock
from labhq.db.enums import MeetingStatus, TranscriptSource
from labhq.db.models import Agent, Meeting, MeetingActionItem, MeetingParticipant, Project
from labhq.db.models import MeetingTranscriptEntry as Entry
from labhq.hierarchy import CEO
from labhq.meetings.actions import DECISION_ACTION
from labhq.meetings.caps import CLOSING_NOTES, COST_CAP_REASON, TURN_CAP_REASON, Spent
from labhq.meetings.cost import meeting_cost_micros
from labhq.meetings.events import MeetingEventKind, MeetingListeners
from labhq.meetings.events import default_listeners as builtin_listeners
from labhq.meetings.kinds import MeetingKind
from labhq.meetings.kinds import default_kinds as builtin_kinds
from labhq.meetings.prompts import Seat, minutes_prompt, room_turn_prompt
from labhq.meetings.proposal import default_proposals
from labhq.meetings.record import record_minutes
from labhq.meetings.reply import InvalidMinutesError, MinutesReply, parse_minutes
from labhq.meetings.runner import (
    BUDGET_REASON,
    INVALID_MINUTES_REASON,
    UNRECORDED_MINUTES_REASON,
    Context,
    MeetingRunner,
    seats_of,
)
from labhq.meetings.settings import MeetingSettings
from labhq.meetings.transcript import add_entry, lines
from labhq.money import format_micros
from labhq.runs import RunService

logger = logging.getLogger(__name__)

FINISHING_STEP = "finishing its current step"

# Reads why an agent cannot answer yet; None means it can. The default knows adopted managers.
type BusyReader = Callable[[Agent], Awaitable[str | None]]

_LOCKS: weakref.WeakKeyDictionary[object, dict[int, asyncio.Lock]] = weakref.WeakKeyDictionary()


async def adopted_busy(agent: Agent) -> str | None:
    """An adopted tmux manager is mid-step while its turn is open (`labhq.adoption.checks`)."""
    state = state_of(agent)
    return FINISHING_STEP if state is not None and state.turn_open else None


class RoomClosedError(RuntimeError):
    pass


@dataclass(frozen=True)
class Pending:
    seat: Seat | None
    turns: int


class DecisionRoom(MeetingRunner):
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        clock: Clock,
        runs: RunService,
        approvals: ApprovalService,
        kinds: Registry[MeetingKind] = builtin_kinds,
        listeners: MeetingListeners = builtin_listeners,
        settings: MeetingSettings | None = None,
        budget_settings: BudgetSettings | None = None,
        busy: BusyReader = adopted_busy,
    ) -> None:
        super().__init__(
            sessions,
            clock=clock,
            runs=runs,
            kinds=kinds,
            listeners=listeners,
            settings=settings,
            budget_settings=budget_settings,
        )
        self._approvals = approvals
        self._busy = busy

    async def run(self, meeting_id: int) -> Meeting:
        """Open an approved room: the CEO speaks first, then the room waits for the owner."""
        await self._begin(meeting_id)
        await self._emit(MeetingEventKind.STARTED, meeting_id)
        await self.advance(meeting_id)
        return await self._load(meeting_id)

    async def advance(self, meeting_id: int) -> None:
        """Run every turn still owed after the owner's latest message, then stop."""
        async with self._lock(meeting_id):
            while True:
                context = await self._context(meeting_id)
                if context is None:
                    return
                pending = await self._pending(context)
                spent = await self._spent(context.meeting_id)
                if spent.cap is not None and spent.total >= spent.cap:
                    await self._finish(context, COST_CAP_REASON, spent)
                    return
                if pending.turns >= self._settings.decision_turn_cap:
                    await self._finish(context, TURN_CAP_REASON, spent)
                    return
                if pending.seat is None:
                    return
                if not await self._may_start(pending.seat.agent_id):
                    await self._end(meeting_id, MeetingStatus.ENDED, BUDGET_REASON)
                    return
                await self._room_turn(context, pending.seat)
                await self._announce_overrun(context.meeting_id)

    async def close(self, meeting_id: int) -> Meeting:
        """Write the minutes and end the room, whoever asked: the owner or the CEO."""
        async with self._lock(meeting_id):
            context = await self._context(meeting_id)
            if context is None:
                raise RoomClosedError(f"meeting {meeting_id} is not an open room")
            return await self._finish(context, None, await self._spent(meeting_id))

    def _lock(self, meeting_id: int) -> asyncio.Lock:
        # Shared by every room object over one database, so a kick and a close never overlap.
        return _LOCKS.setdefault(self._sessions, {}).setdefault(meeting_id, asyncio.Lock())

    async def _load(self, meeting_id: int) -> Meeting:
        async with self._sessions() as db:
            return await db.get_one(Meeting, meeting_id)

    async def _context(self, meeting_id: int) -> Context | None:
        """The room as it stands, or None once it is no longer running."""
        async with self._sessions() as db:
            meeting = await db.get_one(Meeting, meeting_id)
            if meeting.status is not MeetingStatus.RUNNING:
                return None
            project = await db.get_one(Project, meeting.project_id)
            seats = await seats_of(db, meeting_id)
        facilitator = next(s for s in seats if s.agent_id == meeting.facilitator_agent_id)
        return Context(
            meeting_id=meeting_id,
            kind=self._kinds.get(meeting.kind),
            project=project.name,
            agenda=meeting.agenda,
            seats=seats,
            facilitator=facilitator,
        )

    async def _pending(self, context: Context) -> Pending:
        async with self._sessions() as db:
            last_owner = await db.scalar(
                select(func.max(Entry.id)).where(
                    Entry.meeting_id == context.meeting_id, Entry.source == TranscriptSource.OWNER
                )
            )
            answered = set(
                await db.scalars(
                    select(MeetingParticipant.agent_id)
                    .join(Entry, Entry.participant_id == MeetingParticipant.id)
                    .where(
                        Entry.meeting_id == context.meeting_id,
                        Entry.run_id.is_not(None),
                        Entry.id > (last_owner or 0),
                    )
                )
            )
            turns = await db.scalar(
                select(func.count(Entry.id)).where(
                    Entry.meeting_id == context.meeting_id, Entry.run_id.is_not(None)
                )
            )
        seat = next((s for s in context.seats if s.agent_id not in answered), None)
        return Pending(seat, turns or 0)

    async def _room_turn(self, context: Context, seat: Seat) -> None:
        async with self._sessions() as db:
            agent = await db.get_one(Agent, seat.agent_id)
            transcript = await lines(db, context.meeting_id)
            proposal = await self._proposal(db, context.meeting_id)
        reason = await self._busy(agent)
        if reason is not None:
            await self._wait(context.meeting_id, seat, reason)
        try:
            prompt = room_turn_prompt(
                project=context.project,
                seat=seat,
                others=[other for other in context.seats if other is not seat],
                proposal=proposal,
                transcript=transcript,
            )
            text, run_id = await self._ask(seat.agent_id, prompt)
        finally:
            if reason is not None:
                await self._wait(context.meeting_id, None, None)
        await self._say(context.meeting_id, seat, text, run_id)

    async def _proposal(self, db: AsyncSession, meeting_id: int) -> str | None:
        meeting = await db.get_one(Meeting, meeting_id)
        if meeting.pinned_kind is None or meeting.pinned_id is None:
            return None
        described = await default_proposals.get(meeting.pinned_kind)(db, meeting.pinned_id)
        return (
            None
            if described is None
            else f"{meeting.pinned_kind} #{described.id}: {described.text}"
        )

    async def _wait(self, meeting_id: int, seat: Seat | None, reason: str | None) -> None:
        async with self._sessions() as db:
            meeting = await db.get_one(Meeting, meeting_id)
            meeting.waiting_agent_id = seat.agent_id if seat else None
            meeting.waiting_reason = reason
            entry = None
            if seat is not None:
                entry = await add_entry(
                    db,
                    self._clock,
                    meeting_id=meeting_id,
                    source=TranscriptSource.SYSTEM,
                    text=f"Waiting for {seat.name}: {reason}.",
                )
            await db.commit()
        await self._emit(MeetingEventKind.ENTRY_ADDED, meeting_id, entry.id if entry else None)

    async def _say(self, meeting_id: int, seat: Seat, text: str | None, run_id: int) -> None:
        if text:
            await super()._say(meeting_id, seat, text, run_id)
            return
        # Attributed to the seat, so a silent agent counts as having had its turn.
        async with self._sessions() as db:
            participant_id = await _participant_id(db, meeting_id, seat.agent_id)
            entry = await add_entry(
                db,
                self._clock,
                meeting_id=meeting_id,
                source=TranscriptSource.SYSTEM,
                text=f"{seat.name} did not reply (run #{run_id}).",
                participant_id=participant_id,
                run_id=run_id,
            )
            await db.commit()
        await self._emit(MeetingEventKind.ENTRY_ADDED, meeting_id, entry.id)

    async def _spent(self, meeting_id: int) -> Spent:
        async with self._sessions() as db:
            meeting = await db.get_one(Meeting, meeting_id)
            return Spent(
                await meeting_cost_micros(db, meeting_id),
                meeting.cost_cap_micros,
                meeting.estimate_high_micros,
                meeting.over_estimate_at,
            )

    async def _announce_overrun(self, meeting_id: int) -> None:
        """Say once, in the thread, that the room cost more than the high end of its estimate."""
        spent = await self._spent(meeting_id)
        if spent.high is None or spent.total <= spent.high or spent.announced_at is not None:
            return
        async with self._sessions() as db:
            # Conditional, so two callers cannot both announce it.
            claimed = await db.execute(
                update(Meeting)
                .where(Meeting.id == meeting_id, Meeting.over_estimate_at.is_(None))
                .values(over_estimate_at=self._clock.now())
            )
            await db.commit()
        if claimed.rowcount == 1:  # type: ignore[attr-defined]
            await self._note(
                meeting_id,
                f"The room has cost {format_micros(spent.total)}, above the high end of its "
                f"estimate ({format_micros(spent.high)}).",
            )

    async def _finish(self, context: Context, reason: str | None, spent: Spent) -> Meeting:
        """Minutes, then the end; `reason` is why the room closed itself, None if asked to."""
        meeting_id = context.meeting_id
        if reason is not None:
            await self._note(
                meeting_id,
                CLOSING_NOTES[reason].format(
                    spent=format_micros(spent.total), cap=format_micros(spent.cap or 0)
                ),
            )
        assignees = {seat.agent_id for seat in context.seats if seat.role != CEO}
        error: str | None = None
        for _attempt in range(self._settings.minutes_attempts):
            if not await self._may_start(context.facilitator.agent_id):
                return await self._end(meeting_id, MeetingStatus.ENDED, BUDGET_REASON)
            async with self._sessions() as db:
                transcript = await lines(db, meeting_id)
            prompt = minutes_prompt(
                kind=context.kind,
                project=context.project,
                agenda=context.agenda,
                seats=[seat for seat in context.seats if seat.role != CEO],
                transcript=transcript,
                previous_error=error,
            )
            text, run_id = await self._ask(
                context.facilitator.agent_id, prompt, self._settings.minutes_config or None
            )
            # The raw JSON stays out of the thread; the run id on the note is the cost ledger.
            await self._note(meeting_id, f"Minutes written (run #{run_id}).", run_id)
            try:
                minutes = parse_minutes(text, assignees)
            except InvalidMinutesError as invalid:
                error = str(invalid)
                continue
            return await self._close_room(meeting_id, minutes, reason)
        return await self._end(meeting_id, MeetingStatus.FAILED, INVALID_MINUTES_REASON)

    async def _note(self, meeting_id: int, text: str, run_id: int | None = None) -> None:
        async with self._sessions() as db:
            entry = await add_entry(
                db,
                self._clock,
                meeting_id=meeting_id,
                source=TranscriptSource.SYSTEM,
                text=text,
                run_id=run_id,
            )
            await db.commit()
        await self._emit(MeetingEventKind.ENTRY_ADDED, meeting_id, entry.id)

    async def _close_room(
        self, meeting_id: int, minutes: MinutesReply, reason: str | None
    ) -> Meeting:
        async with self._sessions() as db:
            meeting = await db.get_one(Meeting, meeting_id)
            try:
                items = await record_minutes(db, self._clock, meeting, minutes, assign=False)
                meeting.status = MeetingStatus.ENDED
                meeting.end_reason = reason
                meeting.ended_at = self._clock.now()
                await db.commit()
            except Exception:
                logger.exception("the minutes of room %s were not recorded", meeting_id)
                await db.rollback()
                items = None
        if items is None:
            return await self._end(meeting_id, MeetingStatus.FAILED, UNRECORDED_MINUTES_REASON)
        await self._request_confirmations(meeting_id, [item.id for item in items])
        await self._emit(MeetingEventKind.ENDED, meeting_id)
        return await self._load(meeting_id)

    async def _request_confirmations(self, meeting_id: int, item_ids: list[int]) -> None:
        """One owner approval per action item; the task stays unassigned until it is granted."""
        for item_id in item_ids:
            try:
                async with self._sessions() as db:
                    item = await db.get_one(MeetingActionItem, item_id)
                    payload = {
                        "meeting_id": meeting_id,
                        "item_id": item.id,
                        "task_id": item.task_id,
                        "assignee_id": item.assignee_agent_id,
                    }
                approval = await self._approvals.request(DECISION_ACTION, payload)
                async with self._sessions() as db:
                    stored = await db.get_one(MeetingActionItem, item_id)
                    stored.approval_id = approval.id
                    await db.commit()
            except Exception:
                logger.exception(
                    "room %s: no confirmation requested for item %s", meeting_id, item_id
                )


async def _participant_id(db: AsyncSession, meeting_id: int, agent_id: int) -> int | None:
    return await db.scalar(
        select(MeetingParticipant.id).where(
            MeetingParticipant.meeting_id == meeting_id, MeetingParticipant.agent_id == agent_id
        )
    )
