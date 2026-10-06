"""Two teams with live tmux panes, an SDK agent, and a fake tmux server that records keys."""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.adapters.tmux.adapter import session_name
from labhq.adapters.tmux.server import PaneState, TmuxError
from labhq.clock import FakeClock
from labhq.controlkeys import ControlKeyService
from labhq.db import create_engine, session_factory
from labhq.db.enums import AgentStatus, RunStatus
from labhq.db.models import Agent, Project, Run


class FakePanes:
    """The part of the private tmux server the key sender uses; nothing real runs."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, tuple[str, ...], bool]] = []
        self.dead: set[str] = set()
        self.gone: set[str] = set()
        self.text = "mode: auto-accept"

    def send_keys(self, name: str, *keys: str, literal: bool = False) -> None:
        if name in self.gone:
            raise TmuxError("no such session")
        self.sent.append((name, keys, literal))

    def capture(self, name: str) -> str:
        return self.text

    def pane_state(self, name: str) -> PaneState:
        return PaneState(dead=name in self.dead, exit_status=None)


@dataclass
class World:
    sessions: async_sessionmaker[AsyncSession]
    clock: FakeClock
    panes: FakePanes
    service: ControlKeyService
    ids: dict[str, int] = field(default_factory=dict)
    runs: dict[str, int] = field(default_factory=dict)

    def pane(self, name: str) -> str:
        return session_name(self.runs[name])


async def _agent(
    db: AsyncSession,
    clock: FakeClock,
    project: Project | None,
    role: str,
    title: str,
    reports_to: int | None = None,
    adapter: str = "tmux",
) -> Agent:
    now = clock.now()
    agent = Agent(
        project_id=project.id if project else None,
        role=role,
        title=title,
        adapter=adapter,
        config={"agent": "claude-code"} if adapter == "tmux" else {},
        reports_to=reports_to,
        status=AgentStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    db.add(agent)
    await db.flush()
    return agent


@pytest.fixture
async def sessions(database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(database_url)
    try:
        yield session_factory(engine)
    finally:
        await engine.dispose()


@pytest.fixture
async def world(sessions: async_sessionmaker[AsyncSession], clock: FakeClock) -> World:
    panes = FakePanes()
    built = World(sessions, clock, panes, ControlKeyService(sessions, clock, panes))
    async with sessions() as db:
        now = clock.now()
        projects = [
            Project(name=name, repo_path="/r", created_at=now, updated_at=now)
            for name in ("alpha", "beta")
        ]
        db.add_all(projects)
        await db.flush()
        ceo = await _agent(db, clock, None, "ceo", "CEO")
        built.ids["ceo"] = ceo.id
        for team, project in zip(("a", "b"), projects, strict=True):
            manager = await _agent(db, clock, project, "manager", f"Manager {team}", ceo.id)
            lead = await _agent(db, clock, project, "lead", f"Lead {team}", manager.id)
            worker = await _agent(db, clock, project, "worker", f"Worker {team}", lead.id)
            built.ids.update({f"manager_{team}": manager.id, f"lead_{team}": lead.id})
            built.ids[f"worker_{team}"] = worker.id
        sdk = await _agent(db, clock, projects[0], "worker", "SDK", None, adapter="claude")
        built.ids["sdk"] = sdk.id
        for name, agent_id in built.ids.items():
            run = Run(
                agent_id=agent_id,
                adapter="claude" if name == "sdk" else "tmux",
                status=RunStatus.RUNNING,
                created_at=now,
            )
            db.add(run)
            await db.flush()
            built.runs[name] = run.id
        await db.commit()
    return built
