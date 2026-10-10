"""Record validated minutes: decisions, then each action item together with its task.

Everything is added to the caller's transaction. A task that cannot be created raises before
its action item exists, and the caller's rollback takes the whole minutes with it, so an
action item never exists without its task (plan §6).
"""

from sqlalchemy.ext.asyncio import AsyncSession

from labhq.clock import Clock
from labhq.db.models import Meeting, MeetingActionItem, MeetingDecision, Project
from labhq.meetings.reply import MinutesReply
from labhq.work import add_task


async def record_minutes(
    db: AsyncSession,
    clock: Clock,
    meeting: Meeting,
    minutes: MinutesReply,
    *,
    assign: bool = True,
) -> list[MeetingActionItem]:
    """Record the minutes. With `assign=False` each task is created unassigned, so nobody is
    woken: a decision room's items wait for the owner (`labhq.meetings.actions`)."""
    project = await db.get_one(Project, meeting.project_id)
    decisions: list[MeetingDecision] = []
    for position, text in enumerate(minutes.decisions, start=1):
        decision = MeetingDecision(meeting_id=meeting.id, text=text.strip(), position=position)
        db.add(decision)
        decisions.append(decision)
    await db.flush()

    items: list[MeetingActionItem] = []
    for reply in minutes.action_items:
        decision_id = decisions[reply.decision - 1].id if reply.decision is not None else None
        # Created through `labhq.work`, so the assignee is woken as for any assignment.
        task = await add_task(
            db,
            clock,
            project=str(project.id),
            title=reply.title,
            description=f"Action item from {meeting.kind} meeting #{meeting.id}.",
            assignee=reply.assignee if assign else None,
            reason=f"action item from {meeting.kind} meeting #{meeting.id}",
        )
        item = MeetingActionItem(
            meeting_id=meeting.id,
            decision_id=decision_id,
            text=reply.title,
            assignee_agent_id=reply.assignee,
            task_id=task.id,
        )
        db.add(item)
        items.append(item)
    await db.flush()
    return items
