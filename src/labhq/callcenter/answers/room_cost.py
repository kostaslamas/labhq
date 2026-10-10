"""`meeting_cost`: what the latest decision room will cost or has cost, from the same figures as
the widget (issue #202), in short sentences to read aloud."""

import os
from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.clock import Clock
from labhq.db.enums import MeetingStatus
from labhq.db.models import Meeting, Project
from labhq.meetings import default_kinds, get_meeting_settings
from labhq.meetings.figures import RoomFigures, room_figures
from labhq.speech import join_sentences, say_micros, speakable

NO_ROOM = "There is no decision room yet."


def _live_kinds() -> list[str]:
    return [key for key in default_kinds if default_kinds.get(key).live]


def _range(figures: RoomFigures) -> str:
    assert figures.low_micros is not None and figures.high_micros is not None
    label = "equivalent cost" if figures.equivalent_cost else "cost"
    basis = (
        "from what earlier runs cost"
        if figures.source == "history"
        else "a rough guess, as there are too few earlier runs"
    )
    return (
        f"The {label} is expected between {say_micros(figures.low_micros)} and "
        f"{say_micros(figures.high_micros)}, {basis}"
    )


def _plan(figures: RoomFigures) -> str | None:
    if figures.plan_used_percent is None:
        return None
    percent = round(figures.plan_used_percent)
    return f"It runs on your subscription, with {percent} percent of the plan window used"


async def room_cost(db: AsyncSession, clock: Clock, environ: Mapping[str, str] = os.environ) -> str:
    row = (
        await db.execute(
            select(Meeting, Project.name)
            .join(Project, Meeting.project_id == Project.id)
            .where(Meeting.kind.in_(_live_kinds()), Meeting.status != MeetingStatus.CANCELLED)
            .order_by(Meeting.id.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return NO_ROOM
    meeting, project = row
    figures = await room_figures(db, clock, meeting, get_meeting_settings(), environ)
    label = "equivalent cost" if figures.equivalent_cost else "cost"
    cap = f"The hard cap is {say_micros(figures.cap_micros)}" if figures.cap_micros else None
    if meeting.status is MeetingStatus.REQUESTED:
        head = f"The decision room for {project} has not started"
        sentences = [head, _range(figures) if figures.low_micros is not None else None, cap]
    else:
        state = "is running" if meeting.status is MeetingStatus.RUNNING else "is over"
        spent = (
            f"The decision room for {project} {state}. Its {label} so far is "
            f"{say_micros(figures.spent_micros)} over {figures.turns} of {figures.turn_cap} turns"
        )
        sentences = [spent, _range(figures) if figures.low_micros is not None else None, cap]
    return speakable(join_sentences([s for s in (*sentences, _plan(figures)) if s]))
