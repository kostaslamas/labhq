from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass

import httpx
import pytest

from labhq.adapters import default_registry
from labhq.api.app import create_app
from labhq.api.callcenter import router
from labhq.api.deps import ResolverRegistry
from labhq.api.meetings import router as meetings_router
from labhq.api.routes import RouterRegistry
from labhq.api.settings import ApiSettings
from labhq.approvals import ApprovalService
from labhq.ceoorg.background import settled
from labhq.ceoorg.meetings import meeting_service
from labhq.cli.context import Context
from labhq.clock import FakeClock
from labhq.db.enums import AgentStatus
from labhq.db.models import Agent, CeoReport, Project
from tests.api.conftest import OWNER_HEADER
from tests.meetings.conftest import Stage, StagedAdapter

__all__ = ["settled"]


@dataclass(frozen=True)
class Room:
    id: int
    approval_id: int
    project_id: int
    ceo_id: int
    manager_id: int
    report_id: int


@pytest.fixture
def stage() -> Iterator[Stage]:
    """Every `fake` agent answers from this stage; the registry is put back afterwards."""
    staged = Stage()
    original = default_registry._factories["fake"]
    default_registry.register("fake", lambda: StagedAdapter(staged), replace=True)
    yield staged
    default_registry.register("fake", original, replace=True)


@pytest.fixture
async def room(context: Context, clock: FakeClock) -> Room:
    """A decision room the CEO proposed about one of its reports, waiting for the owner."""
    now = clock.now()
    async with context.sessions() as db:
        project = Project(name="atlas", repo_path="/srv/atlas", created_at=now, updated_at=now)
        db.add(project)
        await db.flush()
        agents = [
            Agent(
                project_id=project_id,
                role=role,
                title=title,
                adapter="fake",
                status=AgentStatus.ACTIVE,
                created_at=now,
                updated_at=now,
            )
            for project_id, role, title in ((None, "ceo", "CEO"), (project.id, "manager", "Boss"))
        ]
        db.add_all(agents)
        report = CeoReport(agent_id=None, text="Hire a reviewer.", refs=[], created_at=now)
        db.add(report)
        await db.flush()
        ceo_id, manager_id, report_id = agents[0].id, agents[1].id, report.id
        await db.commit()
    approvals = ApprovalService(context.sessions, clock=context.clock)
    meeting = await meeting_service(context.sessions, context.clock, approvals).request(
        project_id=project.id,
        kind="decision",
        agenda="Hire a reviewer?",
        requested_by=ceo_id,
        pinned=("report", report_id),
    )
    assert meeting.approval_id is not None
    return Room(meeting.id, meeting.approval_id, project.id, ceo_id, manager_id, report_id)


@pytest.fixture
async def client(
    context: Context, resolvers: ResolverRegistry, api_settings: ApiSettings
) -> AsyncIterator[httpx.AsyncClient]:
    routers = RouterRegistry()
    routers.register(router)
    routers.register(meetings_router)
    app = create_app(context, routers=routers, resolvers=resolvers, settings=api_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={OWNER_HEADER: "kostas"},
    ) as http:
        yield http
        await settled()
