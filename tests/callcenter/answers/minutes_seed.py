"""Meetings as rows, for the minutes answer: no agent runs, only what a meeting leaves behind."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from labhq.db.enums import AgentStatus, MeetingStatus, TaskStatus, TranscriptSource
from labhq.db.models import (
    Agent,
    CostEvent,
    Meeting,
    MeetingActionItem,
    MeetingDecision,
    MeetingParticipant,
    MeetingTranscriptEntry,
    Project,
    Run,
    Task,
)


@dataclass(frozen=True)
class Team:
    project_id: int
    lead_id: int


async def add_team(db: AsyncSession, now: datetime, name: str) -> Team:
    project = Project(name=name, repo_path=f"/srv/{name}", created_at=now, updated_at=now)
    db.add(project)
    await db.flush()
    lead = Agent(
        project_id=project.id,
        role="lead",
        title="Backend lead",
        adapter="fake",
        status=AgentStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    db.add(lead)
    await db.flush()
    return Team(project.id, lead.id)


async def add_meeting(
    db: AsyncSession,
    team: Team,
    held_at: datetime,
    *,
    kind: str = "standup",
    status: MeetingStatus = MeetingStatus.ENDED,
    decisions: Sequence[str] = ("Ship the parser first",),
    items: Sequence[str] = ("Write parser tests",),
    cost_micros: int = 0,
) -> int:
    meeting = Meeting(
        project_id=team.project_id,
        kind=kind,
        agenda=f"{kind} agenda",
        status=status,
        facilitator_agent_id=team.lead_id,
        created_at=held_at,
        started_at=held_at,
        ended_at=held_at if status is MeetingStatus.ENDED else None,
    )
    db.add(meeting)
    await db.flush()
    participant = MeetingParticipant(
        meeting_id=meeting.id, agent_id=team.lead_id, display_name="Backend lead"
    )
    db.add(participant)
    await db.flush()
    run = Run(agent_id=team.lead_id, adapter="fake", created_at=held_at)
    db.add(run)
    await db.flush()
    db.add(
        MeetingTranscriptEntry(
            meeting_id=meeting.id,
            participant_id=participant.id,
            source=TranscriptSource.AGENT,
            text="done the parser, next the tests",
            run_id=run.id,
            created_at=held_at,
        )
    )
    if cost_micros:
        db.add(
            CostEvent(
                run_id=run.id,
                agent_id=team.lead_id,
                project_id=team.project_id,
                cost_micros=cost_micros,
                created_at=held_at,
            )
        )
    db.add_all(
        MeetingDecision(meeting_id=meeting.id, text=text, position=position)
        for position, text in enumerate(decisions, start=1)
    )
    for title in items:
        task = Task(
            project_id=team.project_id,
            title=title,
            status=TaskStatus.TODO,
            assignee_id=team.lead_id,
            created_at=held_at,
            updated_at=held_at,
        )
        db.add(task)
        await db.flush()
        db.add(
            MeetingActionItem(
                meeting_id=meeting.id, text=title, assignee_agent_id=team.lead_id, task_id=task.id
            )
        )
    await db.commit()
    return meeting.id
