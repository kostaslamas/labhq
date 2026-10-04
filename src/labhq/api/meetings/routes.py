"""Meetings read through `read_minutes` and join through `add_owner_entry`, as the CLI does."""

from typing import Annotated

from fastapi import APIRouter, Path
from sqlalchemy import select

from labhq.api.deps import ClockDep, ContextDep, OwnerDep, SessionDep
from labhq.api.errors import ApiError
from labhq.api.meetings.schemas import (
    ActionItem,
    Decision,
    JoinBody,
    MeetingDetail,
    MeetingItem,
    Message,
    Participant,
)
from labhq.api.pagination import Page, PageParamsDep, decode_cursor, encode_cursor
from labhq.db.models import Meeting, Project
from labhq.meetings import MeetingClosedError, MeetingNotFoundError, add_owner_entry, read_minutes
from labhq.meetings.minutes import MinutesView

router = APIRouter(prefix="/meetings", tags=["meetings"])

MeetingId = Annotated[int, Path(ge=1)]


def _not_found(meeting_id: int) -> ApiError:
    return ApiError(404, "meeting_not_found", f"There is no meeting {meeting_id}.")


def _item(meeting: Meeting, project_name: str) -> MeetingItem:
    return MeetingItem(
        id=meeting.id,
        kind=meeting.kind,
        project_id=meeting.project_id,
        project_name=project_name,
        status=meeting.status,
        created_at=meeting.created_at,
        started_at=meeting.started_at,
        channel=meeting.channel_adapter,
    )


@router.get("")
async def meetings_list(
    owner: OwnerDep, session: SessionDep, page: PageParamsDep
) -> Page[MeetingItem]:
    """Newest first. The cursor is the last id served, so a new meeting never shifts a page."""
    statement = select(Meeting, Project.name).join(Project, Meeting.project_id == Project.id)
    if page.cursor is not None:
        (after,) = decode_cursor(page.cursor, 1)
        statement = statement.where(Meeting.id < after)
    rows = (
        await session.execute(statement.order_by(Meeting.id.desc()).limit(page.limit + 1))
    ).all()
    served = rows[: page.limit]
    more = len(rows) > page.limit
    return Page(
        items=[_item(meeting, name) for meeting, name in served],
        next_cursor=encode_cursor([served[-1][0].id]) if more else None,
    )


async def _detail(session: SessionDep, meeting_id: int) -> MeetingDetail:
    try:
        view: MinutesView = await read_minutes(session, meeting_id)
    except MeetingNotFoundError as error:
        raise _not_found(meeting_id) from error
    meeting = await session.get_one(Meeting, meeting_id)
    project = await session.get_one(Project, view.project_id)
    by_id = {p.id: p for p in view.participants}
    names = {p.agent_id: p.display_name for p in view.participants if p.agent_id is not None}
    return MeetingDetail(
        **_item(meeting, project.name).model_dump(),
        agenda=view.agenda,
        end_reason=view.end_reason,
        ended_at=view.ended_at,
        participants=[
            Participant(id=p.id, agent_id=p.agent_id, name=p.display_name)
            for p in view.participants
        ],
        messages=[
            Message(
                id=e.id,
                source=e.source,
                speaker=e.speaker,
                agent_id=by_id[e.participant_id].agent_id if e.participant_id in by_id else None,
                text=e.text,
                created_at=e.created_at,
            )
            for e in view.transcript
        ],
        decisions=[Decision(id=d.id, position=d.position, text=d.text) for d in view.decisions],
        action_items=[
            ActionItem(
                id=i.id,
                text=i.text,
                decision_id=i.decision_id,
                assignee_agent_id=i.assignee_agent_id,
                assignee_name=names.get(i.assignee_agent_id or 0),
                task_id=i.task_id,
                task_title=i.task_title,
                task_status=i.task_status,
            )
            for i in view.action_items
        ],
    )


@router.get("/{meeting_id}")
async def meetings_get(
    meeting_id: MeetingId, owner: OwnerDep, session: SessionDep
) -> MeetingDetail:
    """The whole meeting from the database alone, so it reads the same with chat disconnected."""
    return await _detail(session, meeting_id)


@router.post("/{meeting_id}/messages", status_code=201)
async def meetings_join(
    meeting_id: MeetingId,
    body: JoinBody,
    owner: OwnerDep,
    context: ContextDep,
    session: SessionDep,
    clock: ClockDep,
) -> Message:
    """Say something as the owner; the next turns of the meeting see it."""
    if await session.get(Meeting, meeting_id) is None:
        raise _not_found(meeting_id)
    try:
        entry = await add_owner_entry(
            context.sessions, clock, meeting_id=meeting_id, text=body.text
        )
    except MeetingClosedError as error:
        raise ApiError(
            409, "meeting_closed", "This meeting is over; it takes no more messages."
        ) from error
    if entry is None:  # Only an `external_ref` can repeat, and this call sets none.
        raise ApiError(409, "duplicate_message", "That message was already recorded.")
    session.expire_all()
    detail = await _detail(session, meeting_id)
    return next(m for m in detail.messages if m.id == entry.id)
