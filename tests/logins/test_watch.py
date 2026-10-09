"""A run that stopped on a tool's login dialog starts the flow once, not once per pass."""

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.clock import FakeClock
from labhq.db.enums import AgentStatus, RunStatus
from labhq.db.models import Agent, Run
from labhq.logins import LoginService, login_pass, login_tools
from labhq.logins.settings import LoginSettings
from tests.logins.conftest import CODEX_SCREEN, FakePanes, FakeStatus, notifications

SETTINGS = LoginSettings(url_wait_seconds=5, poll_seconds=1)


async def blocked_run(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock, reason: str
) -> None:
    async with sessions() as db:
        agent = Agent(
            role="engineer",
            title="Engineer",
            adapter="tmux",
            status=AgentStatus.ACTIVE,
            created_at=clock.now(),
            updated_at=clock.now(),
        )
        db.add(agent)
        await db.flush()
        db.add(
            Run(
                agent_id=agent.id,
                adapter="tmux",
                status=RunStatus.FAILED,
                created_at=clock.now(),
                finished_at=clock.now(),
                exit={
                    "subtype": "error_blocked",
                    "is_error": True,
                    "terminal_reason": "blocked_dialog",
                    "errors": [reason],
                },
            )
        )
        await db.commit()


async def test_a_run_blocked_on_the_login_dialog_asks_for_the_login_once(
    service: LoginService,
    sessions: async_sessionmaker[AsyncSession],
    clock: FakeClock,
    panes: FakePanes,
    status: FakeStatus,
) -> None:
    reason = login_tools.get("codex").screen_reason
    assert reason is not None
    await blocked_run(sessions, clock, reason)
    panes.next_screen = CODEX_SCREEN
    command = login_tools.get("codex").status
    assert command is not None

    first = await login_pass(sessions, clock, service, settings=SETTINGS)
    status.answers[command] = (0, "Logged in using ChatGPT")
    clock.advance(timedelta(seconds=30))
    second = await login_pass(sessions, clock, service, settings=SETTINGS)
    third = await login_pass(sessions, clock, service, settings=SETTINGS)

    assert (first, second, third) == (1, 0, 0)
    assert len(await notifications(sessions)) == 2  # the link, then the confirmation


async def test_a_run_blocked_on_anything_else_is_left_alone(
    service: LoginService, sessions: async_sessionmaker[AsyncSession], clock: FakeClock
) -> None:
    await blocked_run(sessions, clock, "Claude Code asks whether to trust the working directory")

    assert await login_pass(sessions, clock, service, settings=SETTINGS) == 0
    assert await notifications(sessions) == []
