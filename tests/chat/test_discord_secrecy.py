"""The bot token and webhook tokens stay out of logs, reprs, exceptions and the database."""

import logging

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.chat import ChatError, Persona
from labhq.chat.contract import Speaker
from labhq.db.models.chat import ChatBinding
from tests.chat.conftest import DiscordHarness, discord_settings
from tests.chat.fake_discord import BOT_TOKEN


def _secrets(harness: DiscordHarness) -> list[str]:
    return [BOT_TOKEN, *harness.api.webhook_tokens.values()]


async def test_tokens_appear_in_no_log_line_repr_exception_or_row(
    discord_harness: DiscordHarness,
    sessions: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    adapter = discord_harness.adapter()
    thread = await adapter.open_thread(await adapter.ensure_channel("demo", "Demo"), "Standup")
    await adapter.post(thread, Persona("Alice"), "hello")
    await discord_harness.say(thread.id, Speaker.OWNER, "ok")
    await anext(adapter.replies())

    errors = []
    for failure in (
        httpx.ConnectError(f"cannot reach {discord_harness.api.requests[-1].url}"),
        401,
        500,
    ):
        discord_harness.api.failures = [failure]
        with pytest.raises(ChatError) as raised:
            # The webhook token is cached, so this fails on the execute URL that carries it.
            await adapter.post(thread, Persona("Alice"), "again")
        errors.append(raised.value)
    discord_harness.api.failures = [httpx.ConnectError(f"cannot reach {BOT_TOKEN}")]
    with pytest.raises(ChatError) as raised:
        await adapter.open_thread(thread.channel, "x")
    errors.append(raised.value)
    await adapter.close()

    async with sessions() as db:
        rows = [repr(vars(row)) for row in await db.scalars(select(ChatBinding))]
    settings = discord_settings()
    sinks = {
        "logs": caplog.text,
        "reprs": repr(adapter) + repr(settings) + str(settings) + repr(vars(settings)),
        "exceptions": "".join(f"{error!s}{error!r}{error.__cause__!r}" for error in errors),
        "rows": "".join(rows),
    }
    assert "HTTP Request" in caplog.text  # the scan saw httpx's request lines
    assert "webhooks" in sinks["exceptions"]
    for name, text in sinks.items():
        for secret in _secrets(discord_harness):
            assert secret not in text, f"a token leaked into {name}"


async def test_the_webhook_token_is_redacted_from_httpx_request_logs(
    discord_harness: DiscordHarness, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="httpx")
    adapter = discord_harness.adapter()
    thread = await adapter.open_thread(await adapter.ensure_channel("demo", "Demo"), "Standup")
    await adapter.post(thread, Persona("Alice"), "hello")
    assert "/webhooks/" in caplog.text and "<redacted>" in caplog.text
