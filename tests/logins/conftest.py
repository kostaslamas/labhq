from collections.abc import AsyncIterator, Sequence
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.clock import FakeClock
from labhq.db import create_engine, session_factory
from labhq.db.models import CeoReport, Notification
from labhq.logins import LoginService
from labhq.logins.settings import LoginSettings


@pytest.fixture
async def sessions(database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(database_url)
    try:
        yield session_factory(engine)
    finally:
        await engine.dispose()


class FakePanes:
    """A login pane that prints a scripted screen. It cannot be typed into: there is no send."""

    socket = "fake-socket"

    def __init__(self) -> None:
        self.screens: dict[str, str] = {}
        self.started: list[tuple[str, tuple[str, ...]]] = []
        self.killed: list[str] = []
        self.next_screen = ""
        self.running = True

    def start(self, name: str, argv: Sequence[str], cwd: Path) -> None:
        self.started.append((name, tuple(argv)))
        self.screens[name] = self.next_screen

    def screen(self, name: str) -> str:
        return self.screens.get(name, "")

    def alive(self, name: str) -> bool:
        return self.running and name not in self.killed

    def kill(self, name: str) -> None:
        self.killed.append(name)


class FakeStatus:
    """Answers each tool's status command from a table the test edits to 'log in'."""

    def __init__(self) -> None:
        self.answers: dict[tuple[str, ...], tuple[int, str] | None] = {}
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv: tuple[str, ...], timeout: float) -> tuple[int, str] | None:
        self.calls.append(argv)
        return self.answers.get(argv)


CODEX_URL = "https://auth.openai.com/oauth/authorize?client_id=app&state=abc123"
CODEX_SCREEN = f"Starting local login server\nOpen this link in your browser:\n{CODEX_URL}\n"


@pytest.fixture
def panes() -> FakePanes:
    return FakePanes()


@pytest.fixture
def status() -> FakeStatus:
    return FakeStatus()


@pytest.fixture
def service(
    sessions: async_sessionmaker[AsyncSession],
    clock: FakeClock,
    panes: FakePanes,
    status: FakeStatus,
    tmp_path: Path,
) -> LoginService:
    return LoginService(
        sessions,
        clock,
        panes,
        work_dir=tmp_path / "logins",
        runner=status,
        settings=LoginSettings(url_wait_seconds=5, poll_seconds=1),
    )


async def notifications(sessions: async_sessionmaker[AsyncSession]) -> list[Notification]:
    async with sessions() as db:
        return list(await db.scalars(select(Notification).order_by(Notification.id)))


async def reports(sessions: async_sessionmaker[AsyncSession]) -> list[CeoReport]:
    async with sessions() as db:
        return list(await db.scalars(select(CeoReport).order_by(CeoReport.id)))
