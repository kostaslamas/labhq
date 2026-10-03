import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.clock import FakeClock
from labhq.db.models import Notification
from labhq.notify import Dispatcher, NotifySettings, build_notifier
from tests.approvals.conftest import isolated_git, remote, repo, sessions, world

# The approval trigger test reuses the approvals world, which also needs the git fixtures.
__all__ = ["isolated_git", "remote", "repo", "sessions", "world"]


class Outbound:
    """A MockTransport that records requests and answers with scripted status codes."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.statuses: list[int] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.statuses.pop(0) if self.statuses else 200)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self))


@pytest.fixture
def outbound() -> Outbound:
    return Outbound()


@pytest.fixture
def dispatcher_for(
    sessions: async_sessionmaker[AsyncSession],
    clock: FakeClock,
    tmp_path_factory: pytest.TempPathFactory,
):
    def make(outbound: Outbound, **env: object) -> Dispatcher:
        settings = NotifySettings(**{"kind": "ntfy", **env})  # type: ignore[arg-type]
        notifier = build_notifier(settings, outbound.client(), tmp_path_factory.mktemp("data"))
        return Dispatcher(sessions, notifier, clock=clock, settings=settings)

    return make


async def all_rows(sessions: async_sessionmaker[AsyncSession]) -> list[Notification]:
    async with sessions() as db:
        return list(await db.scalars(select(Notification).order_by(Notification.id)))
