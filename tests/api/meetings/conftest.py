from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
import pytest

from labhq.api.app import create_app
from labhq.api.deps import ResolverRegistry
from labhq.api.meetings import router
from labhq.api.routes import RouterRegistry
from labhq.api.settings import ApiSettings
from labhq.cli.context import Context
from labhq.clock import FakeClock
from labhq.db.enums import AgentStatus, MeetingStatus, TaskStatus, TranscriptSource
from labhq.db.models import (
    Agent,
    Meeting,
    MeetingActionItem,
    MeetingDecision,
    MeetingParticipant,
    MeetingTranscriptEntry,
    Project,
    Task,
)
from tests.api.conftest import OWNER_HEADER

LONG_WORD = "x" * 400


@dataclass(frozen=True)
class Seeded:
    project_id: int
    standup_id: int
    ended_id: int
    lead_id: int
    worker_id: int
    task_id: int


@pytest.fixture
async def seeded(context: Context, clock: FakeClock) -> Seeded:
    """A running standup with a transcript, and an ended one with minutes and a task."""
    now = clock.now()
    async with context.sessions() as db:
        project = Project(name="atlas", repo_path="/srv/atlas", created_at=now, updated_at=now)
        db.add(project)
        await db.flush()
        lead, worker = (
            Agent(
                project_id=project.id,
                role=role,
                title=title,
                adapter="fake",
                status=AgentStatus.ACTIVE,
                created_at=now,
                updated_at=now,
            )
            for role, title in (("lead", "Backend lead"), ("worker", "Worker"))
        )
        db.add_all([lead, worker])
        await db.flush()

        running = Meeting(
            project_id=project.id,
            kind="standup",
            agenda="What is blocked?",
            status=MeetingStatus.RUNNING,
            created_at=now,
            started_at=now,
        )
        ended = Meeting(
            project_id=project.id,
            kind="planning",
            agenda="Plan the parser.",
            status=MeetingStatus.ENDED,
            created_at=now,
            started_at=now,
            ended_at=now,
        )
        db.add_all([running, ended])
        await db.flush()

        seats = {
            (meeting.id, agent.id): MeetingParticipant(
                meeting_id=meeting.id, agent_id=agent.id, display_name=agent.title
            )
            for meeting in (running, ended)
            for agent in (lead, worker)
        }
        db.add_all(seats.values())
        await db.flush()
        for speaker, text in ((lead, LONG_WORD), (worker, "Parser done, tests next.")):
            db.add(
                MeetingTranscriptEntry(
                    meeting_id=running.id,
                    participant_id=seats[(running.id, speaker.id)].id,
                    source=TranscriptSource.AGENT,
                    text=text,
                    created_at=now,
                )
            )
        decision = MeetingDecision(meeting_id=ended.id, text="Ship the parser first", position=1)
        task = Task(
            project_id=project.id,
            title="Write parser tests",
            status=TaskStatus.TODO,
            assignee_id=lead.id,
            created_at=now,
            updated_at=now,
        )
        db.add_all([decision, task])
        await db.flush()
        db.add(
            MeetingActionItem(
                meeting_id=ended.id,
                decision_id=decision.id,
                text="Write parser tests",
                assignee_agent_id=lead.id,
                task_id=task.id,
            )
        )
        await db.commit()
        return Seeded(project.id, running.id, ended.id, lead.id, worker.id, task.id)


@pytest.fixture
async def client(
    context: Context, resolvers: ResolverRegistry, api_settings: ApiSettings
) -> AsyncIterator[httpx.AsyncClient]:
    routers = RouterRegistry()
    routers.register(router)
    app = create_app(context, routers=routers, resolvers=resolvers, settings=api_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={OWNER_HEADER: "kostas"},
    ) as http:
        yield http
