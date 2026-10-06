from collections.abc import Callable
from typing import Any

import httpx
import pytest

from labhq.api.app import create_app
from labhq.api.capacity.router import get_meter, get_settings
from labhq.api.deps import ResolverRegistry
from labhq.api.routes import default_routers
from labhq.api.settings import ApiSettings
from labhq.cli.context import Context
from labhq.db.enums import AgentStatus, RunStatus, WakeupSource, WakeupStatus
from labhq.db.models import Agent, Project, Run, WakeupRequest
from labhq.scheduler.memory import MemoryReading
from labhq.scheduler.settings import SchedulerSettings

GB = 1024**3
OWNER_HEADER = "X-Test-Owner"


def reading(free_percent: float) -> MemoryReading:
    return MemoryReading(total_bytes=16 * GB, available_bytes=int(16 * GB * free_percent / 100))


@pytest.fixture
async def get(context: Context, resolvers: ResolverRegistry, api_settings: ApiSettings) -> Any:
    app = create_app(context, routers=default_routers, resolvers=resolvers, settings=api_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={OWNER_HEADER: "owner"},
    ) as client:

        async def call(free_percent: float, **limits: Any) -> httpx.Response:
            meter: Callable[[], MemoryReading] = lambda: reading(free_percent)  # noqa: E731
            app.dependency_overrides[get_meter] = lambda: meter
            app.dependency_overrides[get_settings] = lambda: SchedulerSettings(**limits)
            return await client.get("/api/capacity")

        yield call


async def seed(context: Context, running: int, pending: int) -> None:
    now = context.clock.now()
    async with context.sessions() as db:
        project = Project(name="atlas", repo_path="/r", created_at=now, updated_at=now)
        db.add(project)
        await db.flush()
        agent = Agent(
            project_id=project.id,
            role="worker",
            title="Worker",
            adapter="fake",
            status=AgentStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        db.add(agent)
        await db.flush()
        for _ in range(running):
            db.add(Run(agent_id=agent.id, adapter="fake", status=RunStatus.RUNNING, created_at=now))
        for n in range(pending):
            db.add(
                WakeupRequest(
                    agent_id=agent.id,
                    source=WakeupSource.TIMER,
                    status=WakeupStatus.PENDING,
                    idempotency_key=f"k{n}",
                    created_at=now,
                    updated_at=now,
                )
            )
        await db.commit()


async def test_reports_the_injected_readings(context: Context, get: Any) -> None:
    await seed(context, running=1, pending=2)
    body = (await get(60, max_running=3, min_free_memory_percent=15)).json()
    assert body == {
        "running": 1,
        "max_running": 3,
        "free_memory_percent": 60.0,
        "min_free_memory_percent": 15.0,
        "paused_for_memory": False,
        "waiting": 0,
    }


async def test_pauses_below_the_floor_and_counts_waiting_wakeups(
    context: Context, get: Any
) -> None:
    await seed(context, running=0, pending=2)
    body = (await get(10, max_running=3, min_free_memory_percent=15)).json()
    assert body["paused_for_memory"] is True
    assert body["free_memory_percent"] == 10.0
    assert body["waiting"] == 2


async def test_wakeups_wait_at_the_cap_without_a_memory_pause(context: Context, get: Any) -> None:
    await seed(context, running=2, pending=1)
    body = (await get(80, max_running=2)).json()
    assert body["paused_for_memory"] is False
    assert (body["running"], body["max_running"], body["waiting"]) == (2, 2, 1)


async def test_a_zero_floor_never_pauses(context: Context, get: Any) -> None:
    body = (await get(1, max_running=2, min_free_memory_percent=0)).json()
    assert body["paused_for_memory"] is False


async def test_requires_the_owner(
    context: Context, resolvers: ResolverRegistry, api_settings: ApiSettings
) -> None:
    app = create_app(context, routers=default_routers, resolvers=resolvers, settings=api_settings)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get("/api/capacity")).status_code == 401
