"""Two labhq instances in one process: two databases, the fake adapter and one shared clock.

The upstream instance ("A") has a CEO and a project whose manager is the remote manager of
node "lab-b". The downstream instance ("B") has its own CEO, project and manager, and polls
A's federation endpoint through an in-process ASGI transport, so nothing touches a network.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest
from alembic import command
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.adapters import AdapterRegistry, FakeAdapter, FakeScript, default_registry
from labhq.adapters.remote import RemoteAdapter
from labhq.agenttools import AgentToolRegistry, ToolContext, bind
from labhq.api.app import create_app
from labhq.api.deps import ResolverRegistry
from labhq.api.settings import ApiSettings
from labhq.budgets import BudgetSettings
from labhq.cli.context import Context
from labhq.clock import FakeClock
from labhq.db import create_engine, session_factory
from labhq.db.enums import AgentStatus
from labhq.db.models import Agent, Project
from labhq.federation.invites import Invites
from labhq.federation.nodes import Nodes
from labhq.federation.poller import PollResult, UpstreamClient, poll_once
from labhq.federation.queue import DatabaseOrderQueue
from labhq.federation.settings import FederationSettings
from labhq.prompts import RoleRegistry
from labhq.roles import register
from labhq.runs import RunService
from labhq.scheduler import Scheduler
from labhq.settings import Settings, sqlite_url
from tests.conftest import alembic_config
from tests.scheduler.conftest import SETTINGS

UPSTREAM_URL = "http://upstream.test"
NODE_NAME = "lab-b"


@dataclass
class Instance:
    name: str
    sessions: async_sessionmaker[AsyncSession]
    clock: FakeClock
    context: Context
    tools: AgentToolRegistry
    scheduler: Scheduler
    fake: FakeScript
    ceo: int = 0
    project: int = 0
    manager: int = 0
    scheduled: list[Scheduler] = field(default_factory=list)

    async def call(self, tool: str, agent_id: int, /, **arguments: object) -> str:
        (spec,) = [spec for spec in self.tools if spec.name == tool]
        context = ToolContext(agent_id, None, self.sessions, self.clock)
        return await bind(spec, context).handler(dict(arguments))

    async def drain(self) -> None:
        """Start every dispatchable wakeup and wait for the runs to end."""
        await self.scheduler.tick()
        await self.scheduler.settle()

    async def get[T](self, model: type[T], row_id: int) -> T:
        async with self.sessions() as db:
            return await db.get_one(model, row_id)

    async def all[T](self, model: type[T]) -> list[T]:
        async with self.sessions() as db:
            return list(await db.scalars(select(model)))


def _migrated(path: Path) -> str:
    """A migrated scratch database. Sync: alembic's env.py runs an event loop of its own."""
    path.parent.mkdir(parents=True, exist_ok=True)
    url = sqlite_url(path)
    command.upgrade(alembic_config(url), "head")
    return url


async def _build(
    name: str, url: str, clock: FakeClock, remote_queue: bool
) -> AsyncIterator[Instance]:
    path = Path(url.rpartition("///")[2])
    engine = create_engine(url)
    sessions = session_factory(engine)
    fake = FakeScript()
    registry: AdapterRegistry = default_registry.copy()
    registry.register("fake", lambda: FakeAdapter(fake), replace=True)
    if remote_queue:
        queue = DatabaseOrderQueue(sessions, clock)
        registry.register("remote", lambda: RemoteAdapter(queue), replace=True)
    tools = AgentToolRegistry()
    register(RoleRegistry(), tools)
    scheduler = Scheduler(
        sessions,
        clock=clock,
        runs=RunService(sessions, clock=clock, registry=registry, agent_tools=tools),
        settings=SETTINGS,
        budget_settings=BudgetSettings(),
    )
    context = Context(Settings(data_dir=path.parent, database_url=url), sessions, clock)
    instance = Instance(name, sessions, clock, context, tools, scheduler, fake)
    now = clock.now()
    async with sessions() as db:
        project = Project(name="lab", repo_path=f"/srv/{name}", created_at=now, updated_at=now)
        ceo = Agent(
            role="ceo",
            title="CEO",
            adapter="fake",
            status=AgentStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        db.add_all([project, ceo])
        await db.flush()
        instance.project, instance.ceo = project.id, ceo.id
        await db.commit()
    try:
        yield instance
    finally:
        await scheduler.shutdown()
        await engine.dispose()


@pytest.fixture
def upstream_url(tmp_path: Path) -> str:
    return _migrated(tmp_path / "a" / "a.sqlite3")


@pytest.fixture
def downstream_url(tmp_path: Path) -> str:
    return _migrated(tmp_path / "b" / "b.sqlite3")


@pytest.fixture
async def upstream(upstream_url: str, clock: FakeClock) -> AsyncIterator[Instance]:
    async for instance in _build("upstream", upstream_url, clock, True):
        yield instance


@pytest.fixture
async def downstream(downstream_url: str, clock: FakeClock) -> AsyncIterator[Instance]:
    async for instance in _build("downstream", downstream_url, clock, False):
        now = clock.now()
        async with instance.sessions() as db:
            manager = Agent(
                project_id=instance.project,
                role="manager",
                title="Site manager",
                reports_to=instance.ceo,
                adapter="fake",
                status=AgentStatus.ACTIVE,
                created_at=now,
                updated_at=now,
            )
            db.add(manager)
            await db.flush()
            instance.manager = manager.id
            await db.commit()
        yield instance


@dataclass
class Pairing:
    upstream: Instance
    downstream: Instance
    key: str
    node_id: int
    # The remote manager on the upstream instance.
    remote_manager: int
    settings: FederationSettings

    def client(self, key: str | None = None) -> UpstreamClient:
        settings = self.settings.model_copy(update={"upstream_key": SecretStr(key or self.key)})
        app = create_app(
            self.upstream.context,
            resolvers=ResolverRegistry(),
            settings=ApiSettings(ui_dir=Path("/nonexistent")),
        )
        return UpstreamClient(settings, transport=httpx.ASGITransport(app=app))

    async def poll(self, key: str | None = None) -> PollResult:
        async with self.client(key) as client:
            return await poll_once(
                self.downstream.sessions, self.downstream.clock, client, self.settings
            )


@pytest.fixture
async def pairing(upstream: Instance, downstream: Instance) -> Pairing:
    invitation = await Invites(downstream.sessions, clock=downstream.clock).create(label="a")
    added = await Nodes(upstream.sessions, clock=upstream.clock).add(
        UPSTREAM_URL.replace("upstream", "lab-b"),
        invitation.key,
        project="lab",
        name=NODE_NAME,
        spend_cap_micros=None,
    )
    settings = FederationSettings(
        upstream_url=UPSTREAM_URL,
        upstream_key=SecretStr(invitation.key),
        upstream_name="Lab A",
    )
    return Pairing(upstream, downstream, invitation.key, added.node.id, added.manager.id, settings)
