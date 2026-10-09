"""The login flow: link out to every channel and the Call Center, confirmed after the login."""

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.clock import FakeClock
from labhq.db.enums import LoginStage
from labhq.logins import LoginService, login_tools
from tests.logins.conftest import (
    CODEX_SCREEN,
    CODEX_URL,
    FakePanes,
    FakeStatus,
    notifications,
    reports,
)


def logged_out(status: FakeStatus, tool: str = "codex") -> tuple[str, ...]:
    command = login_tools.get(tool).status
    assert command is not None
    status.answers[command] = (1, "Not logged in")
    return command


async def test_a_missing_login_sends_one_notification_with_the_link_and_a_call_center_message(
    service: LoginService,
    sessions: async_sessionmaker[AsyncSession],
    panes: FakePanes,
    status: FakeStatus,
) -> None:
    logged_out(status)
    panes.next_screen = CODEX_SCREEN

    outcome = await service.ensure("codex")

    assert outcome.created and outcome.request is not None
    assert outcome.request.url == CODEX_URL
    assert panes.started == [(outcome.request.pane, ("codex", "login"))]
    [sent] = await notifications(sessions)
    assert sent.click_url == CODEX_URL
    assert CODEX_URL in sent.body and "Codex" in sent.title
    [report] = await reports(sessions)
    assert CODEX_URL in report.text and report.refs == ["login:codex"]


async def test_a_logged_in_tool_asks_nobody(
    service: LoginService, sessions: async_sessionmaker[AsyncSession], status: FakeStatus
) -> None:
    command = login_tools.get("codex").status
    assert command is not None
    status.answers[command] = (0, "Logged in using ChatGPT")

    outcome = await service.ensure("codex")

    assert outcome.request is None
    assert await notifications(sessions) == []


async def test_after_the_login_the_recheck_passes_and_the_ceo_is_told(
    service: LoginService,
    sessions: async_sessionmaker[AsyncSession],
    panes: FakePanes,
    status: FakeStatus,
) -> None:
    command = logged_out(status)
    panes.next_screen = CODEX_SCREEN
    outcome = await service.ensure("codex")
    assert outcome.request is not None
    assert await service.recheck_pending() == 0

    status.answers[command] = (0, "Logged in using ChatGPT")
    assert await service.recheck_pending() == 1

    async with sessions() as db:
        stored = await db.get_one(type(outcome.request), outcome.request.id)
    assert stored.stage is LoginStage.COMPLETED and stored.completed_at is not None
    assert panes.killed == [outcome.request.pane]
    bodies = [n.body for n in await notifications(sessions)]
    assert len(bodies) == 2 and "συνδεδεμένο" in bodies[1]
    assert "CEO" in (await reports(sessions))[-1].text


async def test_at_most_one_pending_login_per_tool_and_account(
    service: LoginService,
    sessions: async_sessionmaker[AsyncSession],
    panes: FakePanes,
    status: FakeStatus,
) -> None:
    logged_out(status)
    panes.next_screen = CODEX_SCREEN

    first = await service.ensure("codex")
    again = await service.ensure("codex")
    other_account = await service.ensure("codex", "work")

    assert (first.created, again.created, other_account.created) == (True, False, True)
    assert again.request is not None and first.request is not None
    assert again.request.id == first.request.id
    assert len(await notifications(sessions)) == 2
    assert len(panes.started) == 2


async def test_a_request_expires_with_the_tools_own_timeout(
    service: LoginService,
    sessions: async_sessionmaker[AsyncSession],
    clock: FakeClock,
    panes: FakePanes,
    status: FakeStatus,
) -> None:
    logged_out(status)
    panes.next_screen = CODEX_SCREEN
    first = await service.ensure("codex")
    assert first.request is not None

    clock.advance(timedelta(seconds=login_tools.get("codex").timeout_seconds))
    assert await service.recheck_pending() == 1
    second = await service.ensure("codex")

    assert second.created and second.request is not None
    assert second.request.id != first.request.id
    async with sessions() as db:
        old = await db.get_one(type(first.request), first.request.id)
    assert old.stage is LoginStage.EXPIRED


async def test_no_link_on_the_screen_tells_the_owner_the_command_to_run(
    service: LoginService,
    sessions: async_sessionmaker[AsyncSession],
    status: FakeStatus,
) -> None:
    logged_out(status)

    outcome = await service.ensure("codex")

    assert outcome.request is not None and outcome.request.stage is LoginStage.FAILED
    [sent] = await notifications(sessions)
    assert "codex login" in sent.body and sent.click_url is None


async def test_a_tool_without_a_login_command_says_so(
    service: LoginService, sessions: async_sessionmaker[AsyncSession], panes: FakePanes
) -> None:
    outcome = await service.request("aider")

    assert outcome.request is not None and outcome.request.url is None
    assert panes.started == []
    assert "Aider" in (await notifications(sessions))[0].body


async def test_a_code_prompt_tells_the_owner_to_paste_it_and_labhq_relays_nothing(
    service: LoginService,
    sessions: async_sessionmaker[AsyncSession],
    panes: FakePanes,
    status: FakeStatus,
) -> None:
    logged_out(status, "claude-code")
    command = login_tools.get("claude-code").status
    assert command is not None
    status.answers[command] = (0, '{"loggedIn": false}')
    link = "https://claude.ai/oauth/authorize?code=true&state=s"
    panes.next_screen = f"Open: {link}\nPaste code here if prompted > "

    outcome = await service.ensure("claude-code")

    assert outcome.request is not None and outcome.request.awaits_code
    [sent] = await notifications(sessions)
    assert "τερματικό" in sent.body and "δεν μεταφέρει κωδικούς" in sent.body
    assert not hasattr(panes, "send_keys") and not hasattr(panes, "send")
