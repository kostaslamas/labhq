"""Chat adapters are registered only when their credentials are configured."""

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.chat import ChatContext, Registration, configured_chat_adapters
from labhq.chat.discord import DiscordAdapter
from labhq.clock import FakeClock
from tests.chat.fake_discord import BOT_TOKEN, GUILD_ID, OWNER_ID

DISCORD_ENV = ("LABHQ_DISCORD_BOT_TOKEN", "LABHQ_DISCORD_GUILD_ID", "LABHQ_DISCORD_OWNER_ID")


@pytest.fixture(autouse=True)
def no_discord_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in DISCORD_ENV:
        monkeypatch.delenv(name, raising=False)


def test_without_a_token_discord_is_not_registered_and_nothing_fails() -> None:
    registry = configured_chat_adapters()
    assert "discord" not in registry
    assert list(registry) == []


async def test_with_a_token_discord_is_registered_and_builds(
    monkeypatch: pytest.MonkeyPatch,
    sessions: async_sessionmaker[AsyncSession],
    clock: FakeClock,
) -> None:
    for name, value in zip(DISCORD_ENV, (BOT_TOKEN, GUILD_ID, OWNER_ID), strict=True):
        monkeypatch.setenv(name, value)
    registry = configured_chat_adapters()
    assert list(registry) == ["discord"]
    async with httpx.AsyncClient() as client:
        adapter = registry.get("discord")(ChatContext(sessions, client, clock))
        assert isinstance(adapter, DiscordAdapter)
        await adapter.close()


def test_a_new_service_is_a_new_registration() -> None:
    unconfigured = Registration("slack", lambda: False, lambda _context: None)  # type: ignore[arg-type,return-value]
    configured = Registration("matrix", lambda: True, lambda _context: None)  # type: ignore[arg-type,return-value]
    assert list(configured_chat_adapters((unconfigured, configured))) == ["matrix"]


def test_the_documented_invite_link_grants_exactly_the_permissions_used() -> None:
    from labhq.chat.discord.adapter import BOT_PERMISSIONS
    from tests.conftest import REPO_ROOT

    doc = (REPO_ROOT / "docs" / "checks" / "discord.md").read_text(encoding="utf-8")
    assert f"permissions={BOT_PERMISSIONS}" in doc
    assert "Message Content Intent" in doc
