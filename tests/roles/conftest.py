"""An org to put to work: a CEO, two projects with their teams, and role tools bound to it."""

from collections.abc import AsyncIterator, Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.adapters import AgentTool
from labhq.adoption import Adoptions
from labhq.agenttools import AgentToolRegistry, ToolContext, bind
from labhq.approvals import ApprovalService, default_actions, default_confirmations
from labhq.approvals.executors import Executor, default_executors
from labhq.approvals.registry import Registry
from labhq.ceoorg.settings import CeoSettings
from labhq.clock import FakeClock
from labhq.db import create_engine, session_factory
from labhq.db.enums import AgentStatus
from labhq.db.models import Agent, Approval, Project, Task, WakeupRequest
from labhq.hierarchy import HierarchySettings
from labhq.prompts import RoleRegistry
from labhq.roles import RoleServices, register

CEILING = 5_000_000


@dataclass(frozen=True)
class OrgServices(RoleServices):
    """The role services with the process table replaced by a list the test fills."""

    processes: Callable[[], Iterable[Any]] = list

    def adoptions(self, context: ToolContext) -> Adoptions:
        return Adoptions(
            context.sessions,
            clock=context.clock,
            approvals=self.approvals(context),
            processes=self.processes,
        )


@dataclass
class Org:
    sessions: async_sessionmaker[AsyncSession]
    clock: FakeClock
    tools: AgentToolRegistry
    executors: Registry[Executor]
    ceo: int
    # The `site` project: manager, two leads with a worker each.
    site: int
    manager: int
    lead: int
    worker: int
    other_lead: int
    other_worker: int
    site_task: int
    # The `shop` project, someone else's.
    shop: int
    shop_manager: int
    shop_worker: int
    shop_task: int
    # The one folder the CEO may browse and add projects from.
    root: Path
    # What the process table holds: a test appends the CLI processes it wants discovered.
    processes: list[Any]

    def tool(self, tool: str, agent_id: int) -> AgentTool:
        (spec,) = [spec for spec in self.tools if spec.name == tool]
        return bind(spec, ToolContext(agent_id, None, self.sessions, self.clock))

    async def call(self, tool: str, agent_id: int, /, **arguments: object) -> str:
        return await self.tool(tool, agent_id).handler(dict(arguments))

    async def all[T](self, model: type[T]) -> list[T]:
        async with self.sessions() as db:
            return list(await db.scalars(select(model)))

    async def get[T](self, model: type[T], row_id: int) -> T:
        async with self.sessions() as db:
            return await db.get_one(model, row_id)

    async def approvals(self) -> list[Approval]:
        return await self.all(Approval)

    async def wakeups(self) -> list[WakeupRequest]:
        return await self.all(WakeupRequest)


@pytest.fixture
async def sessions(database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(database_url)
    try:
        yield session_factory(engine)
    finally:
        await engine.dispose()


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The infra project's directory goes here, never into the developer's data."""
    path = tmp_path / "data"
    monkeypatch.setenv("LABHQ_DATA_DIR", str(path))
    monkeypatch.delenv("LABHQ_DATABASE_URL", raising=False)
    return path


def _agent(
    clock: FakeClock, role: str, title: str, project: int | None, reports_to: int | None
) -> Agent:
    now = clock.now()
    return Agent(
        project_id=project,
        role=role,
        title=title,
        reports_to=reports_to,
        adapter="fake",
        status=AgentStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )


async def _add[T](db: AsyncSession, row: T) -> T:
    db.add(row)
    await db.flush()
    return row


@pytest.fixture
async def org(sessions: async_sessionmaker[AsyncSession], clock: FakeClock, tmp_path: Path) -> Org:
    now = clock.now()
    root = tmp_path / "projects"
    root.mkdir()
    processes: list[Any] = []
    async with sessions() as db:
        site = await _add(
            db, Project(name="site", repo_path="/srv/site", created_at=now, updated_at=now)
        )
        shop = await _add(
            db, Project(name="shop", repo_path="/srv/shop", created_at=now, updated_at=now)
        )
        ceo = await _add(db, _agent(clock, "ceo", "CEO", None, None))
        manager = await _add(db, _agent(clock, "manager", "Site manager", site.id, ceo.id))
        lead = await _add(db, _agent(clock, "lead", "Backend lead", site.id, manager.id))
        worker = await _add(db, _agent(clock, "worker", "Backend dev", site.id, lead.id))
        other_lead = await _add(db, _agent(clock, "lead", "Design lead", site.id, manager.id))
        other_worker = await _add(db, _agent(clock, "worker", "Designer", site.id, other_lead.id))
        shop_manager = await _add(db, _agent(clock, "manager", "Shop manager", shop.id, ceo.id))
        shop_lead = await _add(db, _agent(clock, "lead", "Shop lead", shop.id, shop_manager.id))
        shop_worker = await _add(db, _agent(clock, "worker", "Shop dev", shop.id, shop_lead.id))
        site_task = await _add(
            db, Task(project_id=site.id, title="Login", created_at=now, updated_at=now)
        )
        shop_task = await _add(
            db, Task(project_id=shop.id, title="Cart", created_at=now, updated_at=now)
        )
        await db.commit()

    executors = default_executors.copy()

    def approvals(context: ToolContext) -> ApprovalService:
        return ApprovalService(
            context.sessions,
            clock=context.clock,
            actions=default_actions.copy(),
            executors=executors,
            confirmations=default_confirmations.copy(),
        )

    services = OrgServices(
        approvals=approvals,
        ceo_settings=lambda: CeoSettings(budget_ceiling_micros=CEILING),
        browse_roots=lambda: [root],
        processes=lambda: processes,
        hierarchy_settings=lambda: HierarchySettings(
            approve_new_agents=True, max_team_size=8, org_adapter="fake"
        ),
        adapters=lambda: ["fake"],
    )
    tools = AgentToolRegistry()
    register(RoleRegistry(), tools, services)
    return Org(
        sessions,
        clock,
        tools,
        executors,
        ceo.id,
        site.id,
        manager.id,
        lead.id,
        worker.id,
        other_lead.id,
        other_worker.id,
        site_task.id,
        shop.id,
        shop_manager.id,
        shop_worker.id,
        shop_task.id,
        root,
        processes,
    )
