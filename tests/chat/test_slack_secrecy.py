"""The bot token, app token and socket ticket stay out of logs, reprs, exceptions and rows."""

import logging
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.chat import ChatError, Persona
from labhq.chat.contract import Speaker
from labhq.clock import FakeClock
from labhq.db.models.chat import ChatBinding
from tests.chat.fake_slack import APP_TOKEN, BOT_TOKEN, SOCKET_URL, SlackHarness, slack_settings

SECRETS = (BOT_TOKEN, APP_TOKEN, "socket-ticket-secret")


@pytest.fixture
async def slack(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock
) -> AsyncIterator[SlackHarness]:
    harness = SlackHarness(sessions, clock)
    async with harness.client:
        yield harness


async def test_tokens_appear_in_no_log_line_repr_exception_or_row(
    slack: SlackHarness,
    sessions: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    adapter = slack.adapter()
    thread = await adapter.open_thread(await adapter.ensure_channel("demo", "Demo"), "Standup")
    await adapter.post(thread, Persona("Alice"), "hello")
    slack.socket.deliver(Speaker.OWNER, thread.id, "ok")
    await anext(adapter.replies())

    errors = []
    for failure in (
        httpx.ConnectError(f"cannot reach {BOT_TOKEN} {APP_TOKEN} {SOCKET_URL}"),
        401,
        500,
    ):
        slack.api.failures = [failure]
        with pytest.raises(ChatError) as raised:
            await adapter.post(thread, Persona("Alice"), "again")
        errors.append(raised.value)
    await adapter.close()
    bad = slack.adapter(bot_token="xoxb-wrong", app_token="xapp-wrong")
    with pytest.raises(ChatError, match="invalid_auth") as raised:
        await bad.ensure_channel("other", "Other")
    errors.append(raised.value)

    async with sessions() as db:
        rows = [repr(vars(row)) for row in await db.scalars(select(ChatBinding))]
    settings = slack_settings()
    sinks = {
        "logs": caplog.text,
        "reprs": repr(adapter) + repr(vars(adapter)) + repr(settings) + str(settings),
        "exceptions": "".join(f"{error!s}{error!r}{error.__cause__!r}" for error in errors),
        "rows": "".join(rows),
    }
    assert "HTTP Request" in caplog.text  # the scan saw httpx's request lines
    assert "chat.postMessage" in sinks["exceptions"]
    for name, text in sinks.items():
        for secret in SECRETS:
            assert secret not in text, f"a secret leaked into {name}"


async def test_each_token_goes_only_to_its_own_method_as_a_bearer_header(
    slack: SlackHarness,
) -> None:
    adapter = slack.adapter()
    thread = await adapter.open_thread(await adapter.ensure_channel("demo", "Demo"), "Standup")
    slack.socket.deliver(Speaker.OWNER, thread.id, "ok")
    await anext(adapter.replies())
    await adapter.close()

    for request in slack.api.requests:
        assert not any(secret in str(request.url) for secret in SECRETS)
        token = APP_TOKEN if request.url.path.endswith("apps.connections.open") else BOT_TOKEN
        assert request.headers["Authorization"] == f"Bearer {token}"
