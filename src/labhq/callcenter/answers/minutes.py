"""`meeting_minutes`: what a meeting decided and who does what next, in short sentences.

The meeting is picked from what the owner said: a meeting number, a kind, a project, a day
phrase and "last". Nothing named means the latest meeting. When a reference fits more than one
meeting the answer is a short question back, never a guess. Days are UTC, as in `brief`:
labhq keeps no owner time zone.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.approvals.registry import Registry
from labhq.callcenter.answers.phrasing import FREE_TEXT_WORDS, clean, name_list
from labhq.clock import Clock
from labhq.db.enums import MeetingStatus, TaskStatus
from labhq.db.models import Agent, Meeting, Project
from labhq.meetings import MeetingKind, MinutesView, read_minutes
from labhq.meetings import default_kinds as builtin_kinds
from labhq.meetings.room import COST_CAP_REASON, TURN_CAP_REASON
from labhq.meetings.runner import BUDGET_REASON, INVALID_MINUTES_REASON, UNRECORDED_MINUTES_REASON
from labhq.speech import join_sentences, say_ago, say_count, say_micros, speakable

LISTED_DECISIONS = 5
LISTED_ITEMS = 5
LISTED_CHOICES = 3


@dataclass(frozen=True)
class Window:
    """Part of a day, `days_back` days before today, from `start_hour` up to `end_hour`."""

    days_back: int
    start_hour: int
    end_hour: int


# Data, not branches: a new day phrase is a new row. Longer phrases are tried first.
DAY_PHRASES: dict[str, Window] = {
    "this morning": Window(0, 0, 12),
    "this afternoon": Window(0, 12, 18),
    "this evening": Window(0, 18, 24),
    "tonight": Window(0, 18, 24),
    "today": Window(0, 0, 24),
    "yesterday morning": Window(1, 0, 12),
    "yesterday afternoon": Window(1, 12, 18),
    "yesterday evening": Window(1, 18, 24),
    "yesterday": Window(1, 0, 24),
}
LATEST_WORDS = ("last", "latest", "most recent", "previous")
# How a kind may be said aloud when it differs from its key.
KIND_ALIASES: dict[str, str] = {"stand up": "standup", "stand-up": "standup"}

_MEETING_NUMBER = re.compile(r"\b(?:meeting\s*(?:number\s*)?#?|m\s?)(\d+)\b")

_STATUS_SENTENCES: dict[MeetingStatus, str] = {
    MeetingStatus.ENDED: "The {kind} for {project} ended {ago}",
    MeetingStatus.RUNNING: "The {kind} for {project} is still running. It started {ago}",
    MeetingStatus.REQUESTED: "The {kind} for {project} is waiting for your approval to start",
    MeetingStatus.FAILED: "The {kind} for {project} failed {ago}",
    MeetingStatus.CANCELLED: "The {kind} for {project} was cancelled {ago}",
}
_END_REASONS: dict[str, str] = {
    BUDGET_REASON: "It stopped early at the budget limit",
    INVALID_MINUTES_REASON: "Its minutes could not be read",
    UNRECORDED_MINUTES_REASON: "Its minutes could not be recorded",
    COST_CAP_REASON: "It stopped at its cost cap",
    TURN_CAP_REASON: "It closed at its turn cap",
}
_TASK_STATUSES: dict[TaskStatus, str] = {
    TaskStatus.BACKLOG: "in the backlog",
    TaskStatus.TODO: "not started",
    TaskStatus.IN_PROGRESS: "in progress",
    TaskStatus.IN_REVIEW: "in review",
    TaskStatus.BLOCKED: "blocked",
    TaskStatus.DONE: "done",
    TaskStatus.CANCELLED: "cancelled",
}


def meeting_ref(meeting_id: int) -> str:
    return f"M{meeting_id}"


@dataclass(frozen=True)
class Reference:
    """What the owner said about which meeting, read into filters."""

    said: str = ""
    meeting_id: int | None = None
    kind: str | None = None
    project_id: int | None = None
    project_name: str | None = None
    day_phrase: str | None = None
    window: tuple[datetime, datetime] | None = None
    latest: bool = False

    @property
    def names_a_meeting(self) -> bool:
        """False when nothing said narrows the search: then the latest meeting is meant."""
        return any(f is not None for f in (self.kind, self.project_id, self.window))


@dataclass(frozen=True)
class Candidate:
    id: int
    kind: str
    project: str
    held: datetime


def _contains(text: str, phrase: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(phrase)}s?(?!\w)", text) is not None


def _window(phrase: Window, now: datetime) -> tuple[datetime, datetime]:
    day = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=phrase.days_back)
    return day + timedelta(hours=phrase.start_hour), day + timedelta(hours=phrase.end_hour)


async def _project(db: AsyncSession, text: str) -> tuple[int, str] | None:
    """The project whose name the owner said; the longest name wins over a shorter one in it."""
    rows = (await db.execute(select(Project.id, Project.name))).all()
    said = [(len(name), pid, name) for pid, name in rows if _contains(text, name.lower())]
    if not said:
        return None
    _, project_id, name = max(said)
    return project_id, name


async def parse_reference(
    db: AsyncSession, clock: Clock, said: str, kinds: Registry[MeetingKind] = builtin_kinds
) -> Reference:
    text = said.lower().replace("'s", "")
    for alias, key in KIND_ALIASES.items():
        text = text.replace(alias, key)
    number = _MEETING_NUMBER.search(text)
    phrase = next(
        (p for p in sorted(DAY_PHRASES, key=len, reverse=True) if _contains(text, p)), None
    )
    project = await _project(db, text)
    return Reference(
        said=said,
        meeting_id=int(number.group(1)) if number else None,
        kind=next((key for key in kinds if _contains(text, key.lower())), None),
        project_id=project[0] if project else None,
        project_name=project[1] if project else None,
        day_phrase=phrase,
        window=_window(DAY_PHRASES[phrase], clock.now()) if phrase else None,
        latest=any(_contains(text, word) for word in LATEST_WORDS),
    )


async def find_candidates(db: AsyncSession, reference: Reference) -> list[Candidate]:
    """Meetings that fit; one per project unless a day was named without "last"."""
    held = func.coalesce(Meeting.started_at, Meeting.created_at)
    filters: list[ColumnElement[bool]] = [Meeting.status != MeetingStatus.CANCELLED]
    if reference.kind is not None:
        filters.append(Meeting.kind == reference.kind)
    if reference.project_id is not None:
        filters.append(Meeting.project_id == reference.project_id)
    if reference.window is not None:
        filters.extend((held >= reference.window[0], held < reference.window[1]))
    rank = (
        func.row_number()
        .over(partition_by=Meeting.project_id, order_by=(held.desc(), Meeting.id.desc()))
        .label("rank")
    )
    fitting = (
        select(Meeting.id, Meeting.kind, Project.name, held.label("held"), rank)
        .join(Project, Project.id == Meeting.project_id)
        .where(*filters)
        .subquery()
    )
    query = select(fitting.c.id, fitting.c.kind, fitting.c.name, fitting.c.held)
    if reference.window is None or reference.latest:
        query = query.where(fitting.c.rank == 1)
    rows = await db.execute(query.order_by(fitting.c.held.desc(), fitting.c.id.desc()))
    candidates = [Candidate(*row) for row in rows.all()]
    # Nothing named: the latest meeting, whichever project held it.
    return candidates if reference.names_a_meeting else candidates[:1]


def _noun(reference: Reference) -> str:
    return clean(reference.kind) if reference.kind else "meeting"


def _nothing(reference: Reference) -> str:
    if not reference.names_a_meeting:
        return "No meeting has been held yet."
    where = f" for {clean(reference.project_name)}" if reference.project_name else ""
    when = f" {reference.day_phrase}" if reference.day_phrase else ""
    return f"I found no {_noun(reference)}{where}{when}."


def _which_one(reference: Reference, candidates: list[Candidate], clock: Clock) -> str:
    parts = [f"{say_count(len(candidates), _noun(reference)).capitalize()} fit"]
    for candidate in candidates[:LISTED_CHOICES]:
        ago = say_ago(clock.now() - candidate.held)
        parts.append(
            f"Meeting {meeting_ref(candidate.id)} is the {clean(candidate.kind)} "
            f"for {clean(candidate.project)}, {ago}"
        )
    if len(candidates) > LISTED_CHOICES:
        parts.append(f"{len(candidates) - LISTED_CHOICES} more fit too")
    parts.append("Which one? Say the meeting number or the project")
    return join_sentences(parts)


def _when(view: MinutesView) -> datetime:
    return view.ended_at or view.started_at or view.created_at


async def _assignees(db: AsyncSession, view: MinutesView) -> dict[int, str]:
    ids = {item.assignee_agent_id for item in view.action_items} - {None}
    if not ids:
        return {}
    rows = await db.execute(select(Agent.id, Agent.title).where(Agent.id.in_(ids)))
    return {agent_id: clean(title) for agent_id, title in rows.all()}


def _who_took_part(view: MinutesView) -> str | None:
    names = [clean(p.display_name) for p in view.participants if p.agent_id is not None]
    if any(p.agent_id is None for p in view.participants):
        names.append("you")
    if not names:
        return None
    return f"{name_list(names)} took part"


def _recorded(count: int, noun: str) -> str:
    return f"{say_count(count, noun).capitalize()} {'was' if count == 1 else 'were'} recorded"


def _decisions(view: MinutesView) -> list[str]:
    total = len(view.decisions)
    parts = [_recorded(total, "decision")]
    parts += [
        f"Decision {decision.position}: {clean(decision.text, FREE_TEXT_WORDS)}"
        for decision in view.decisions[:LISTED_DECISIONS]
    ]
    if total > LISTED_DECISIONS:
        parts.append(f"{total - LISTED_DECISIONS} more decisions are in the minutes")
    return parts


def _action_items(view: MinutesView, names: dict[int, str]) -> list[str]:
    total = len(view.action_items)
    parts = [_recorded(total, "action item")]
    for item in view.action_items[:LISTED_ITEMS]:
        assignee = item.assignee_agent_id
        who = (
            f"assigned to {names.get(assignee, f'agent {assignee}')}" if assignee else "unassigned"
        )
        status = _TASK_STATUSES.get(item.task_status, clean(item.task_status.value))
        parts.append(f"{clean(item.text)}, {who}. Task T{item.task_id} is {status}")
    if total > LISTED_ITEMS:
        parts.append(f"{total - LISTED_ITEMS} more action items are in the minutes")
    return parts


async def say_minutes(db: AsyncSession, clock: Clock, view: MinutesView, project: str) -> str:
    ago = say_ago(clock.now() - _when(view))
    parts = [
        _STATUS_SENTENCES[view.status].format(
            kind=clean(view.kind), project=clean(project), ago=ago
        )
    ]
    if view.end_reason:
        parts.append(_END_REASONS.get(view.end_reason, f"It ended with {clean(view.end_reason)}"))
    who = _who_took_part(view)
    if who:
        parts.append(who)
    if view.status in (MeetingStatus.REQUESTED, MeetingStatus.RUNNING):
        parts.append("Its minutes are not written yet")
    else:
        parts += _decisions(view)
        parts += _action_items(view, await _assignees(db, view))
    parts.append(f"It cost {say_micros(view.cost_micros)}")
    return join_sentences(parts)


async def _by_number(db: AsyncSession, clock: Clock, meeting_id: int) -> str:
    row = (
        await db.execute(
            select(Meeting.id, Project.name)
            .join(Project, Project.id == Meeting.project_id)
            .where(Meeting.id == meeting_id)
        )
    ).first()
    if row is None:
        return f"I have no meeting {meeting_ref(meeting_id)}."
    return await say_minutes(db, clock, await read_minutes(db, meeting_id), row.name)


async def meeting_minutes(
    db: AsyncSession,
    clock: Clock,
    said: str | None = None,
    *,
    kinds: Registry[MeetingKind] = builtin_kinds,
) -> str:
    """The minutes of the meeting the owner named, or a short question when several fit."""
    reference = await parse_reference(db, clock, " ".join((said or "").split()), kinds)
    if reference.meeting_id is not None:
        return speakable(await _by_number(db, clock, reference.meeting_id))
    candidates = await find_candidates(db, reference)
    if not candidates:
        return speakable(_nothing(reference))
    if len(candidates) > 1:
        return speakable(_which_one(reference, candidates, clock))
    chosen = candidates[0]
    view = await read_minutes(db, chosen.id)
    return speakable(await say_minutes(db, clock, view, chosen.project))
