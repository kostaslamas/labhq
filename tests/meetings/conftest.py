from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.adapters import AdapterResult, FakeAdapter, FakeScript, RunRequest, default_registry
from labhq.approvals import ApprovalService, Registry
from labhq.clock import FakeClock
from labhq.db import create_engine, session_factory
from labhq.db.enums import AgentStatus
from labhq.db.models import Agent, Meeting, Project
from labhq.meetings import (
    MeetingKind,
    MeetingListeners,
    MeetingRunner,
    MeetingService,
    MeetingSettings,
    default_kinds,
)
from labhq.memory import AgentMemory
from labhq.runs import RunService

MINUTES_MARKER = "Write its minutes."


class TickingClock(FakeClock):
    """Moves one second on every read, so each recorded instant is distinct."""

    def now(self) -> datetime:
        return self.advance(timedelta(seconds=1))


@dataclass
class Stage:
    """Scripts the fake agents of a meeting and records what they were asked."""

    script: FakeScript = field(default_factory=FakeScript)
    # Popped one per minutes request; an empty list means "no reply".
    minutes: list[str] = field(default_factory=list)
    on_start: list[Callable[[RunRequest], Awaitable[None]]] = field(default_factory=list)
    prompts: list[str] = field(default_factory=list)

    def turn_prompts(self) -> list[str]:
        return [prompt for prompt in self.prompts if MINUTES_MARKER not in prompt]

    def minutes_prompts(self) -> list[str]:
        return [prompt for prompt in self.prompts if MINUTES_MARKER in prompt]

    def reply(self, request: RunRequest) -> str | None:
        if MINUTES_MARKER in request.prompt:
            return self.minutes.pop(0) if self.minutes else None
        return f"turn {len(self.turn_prompts())}: done the parser, next the tests, no blockers"


class StagedAdapter(FakeAdapter):
    def __init__(self, stage: Stage) -> None:
        super().__init__(stage.script)
        self._stage = stage

    async def start(self, request: RunRequest) -> None:
        self._stage.prompts.append(request.prompt)
        for hook in self._stage.on_start:
            await hook(request)
        await super().start(request)

    def _final_result(self) -> AdapterResult:
        assert self._request is not None
        return replace(super()._final_result(), text=self._stage.reply(self._request))


@dataclass
class World:
    sessions: async_sessionmaker[AsyncSession]
    clock: TickingClock
    stage: Stage
    kinds: Registry[MeetingKind]
    approvals: ApprovalService
    listeners: MeetingListeners
    runner: MeetingRunner
    service: MeetingService
    project_id: int
    manager_id: int
    lead_id: int
    worker_id: int

    def minutes_json(self, *, decision: str = "Ship the parser first") -> str:
        return (
            f'{{"decisions": ["{decision}"], "action_items": [{{"title": "Write parser '
            f'tests", "assignee": {self.lead_id}, "decision": 1}}]}}'
        )

    async def approved_meeting(
        self, kind: str = "standup", participants: list[int] | None = None
    ) -> int:
        meeting = await self.service.request(
            project_id=self.project_id, kind=kind, participants=participants
        )
        assert meeting.approval_id is not None
        await self.approvals.approve(meeting.approval_id, decider="owner", confirmation="voice")
        return meeting.id

    async def meeting(self, meeting_id: int) -> Meeting:
        async with self.sessions() as db:
            return await db.get_one(Meeting, meeting_id)


@pytest.fixture
async def sessions(database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(database_url)
    try:
        yield session_factory(engine)
    finally:
        await engine.dispose()


async def _agent(db: AsyncSession, now: datetime, project: Project, role: str, title: str) -> int:
    agent = Agent(
        project_id=project.id,
        role=role,
        title=title,
        adapter="fake",
        status=AgentStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    db.add(agent)
    await db.flush()
    return agent.id


@pytest.fixture
async def world(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock, tmp_path: Path
) -> World:
    ticking = TickingClock(clock.now())
    stage = Stage()
    registry = default_registry.copy()
    registry.register("fake", lambda: StagedAdapter(stage), replace=True)
    async with sessions() as db:
        now = ticking.now()
        project = Project(name="demo", repo_path="/srv/demo", created_at=now, updated_at=now)
        db.add(project)
        await db.flush()
        # The worker is in the project but not a default standup participant.
        worker_id = await _agent(db, now, project, "worker", "Worker")
        lead_id = await _agent(db, now, project, "lead", "Backend lead")
        manager_id = await _agent(db, now, project, "manager", "Manager")
        await db.commit()
    kinds = default_kinds.copy()
    listeners = MeetingListeners()
    settings = MeetingSettings()
    approvals = ApprovalService(sessions, clock=ticking)
    runner = MeetingRunner(
        sessions,
        clock=ticking,
        # Managers and leads keep memory; it must not reach the developer's data directory.
        runs=RunService(
            sessions,
            clock=ticking,
            registry=registry,
            memory=AgentMemory(tmp_path / "agents"),
        ),
        kinds=kinds,
        listeners=listeners,
        settings=settings,
    )
    service = MeetingService(
        sessions,
        clock=ticking,
        approvals=approvals,
        runner=runner,
        kinds=kinds,
        settings=settings,
    )
    return World(
        sessions=sessions,
        clock=ticking,
        stage=stage,
        kinds=kinds,
        approvals=approvals,
        listeners=listeners,
        runner=runner,
        service=service,
        project_id=project.id,
        manager_id=manager_id,
        lead_id=lead_id,
        worker_id=worker_id,
    )
