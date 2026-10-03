"""Slack is registered only with both tokens, and its manifest grants exactly what it uses."""

import re
from collections.abc import Iterator

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.chat import ChatContext, configured_chat_adapters
from labhq.chat.slack import APP_SCOPES, BOT_EVENTS, BOT_SCOPES, SlackAdapter
from labhq.clock import FakeClock
from tests.chat.fake_slack import APP_TOKEN, BOT_TOKEN, OWNER_ID
from tests.conftest import REPO_ROOT

SLACK_ENV = {
    "LABHQ_SLACK_BOT_TOKEN": BOT_TOKEN,
    "LABHQ_SLACK_APP_TOKEN": APP_TOKEN,
    "LABHQ_SLACK_OWNER_ID": OWNER_ID,
}
MANIFEST = REPO_ROOT / "docs" / "guide" / "slack-manifest.yaml"


@pytest.fixture(autouse=True)
def no_chat_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in (*SLACK_ENV, "LABHQ_DISCORD_BOT_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    yield


def test_without_tokens_slack_is_not_registered_and_nothing_fails() -> None:
    assert "slack" not in configured_chat_adapters()


def test_a_bot_token_alone_does_not_register_slack(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LABHQ_SLACK_BOT_TOKEN", BOT_TOKEN)
    assert "slack" not in configured_chat_adapters()


async def test_with_both_tokens_slack_is_registered_and_builds(
    monkeypatch: pytest.MonkeyPatch,
    sessions: async_sessionmaker[AsyncSession],
    clock: FakeClock,
) -> None:
    for name, value in SLACK_ENV.items():
        monkeypatch.setenv(name, value)
    registry = configured_chat_adapters()
    assert list(registry) == ["slack"]
    async with httpx.AsyncClient() as client:
        adapter = registry.get("slack")(ChatContext(sessions, client, clock))
        assert isinstance(adapter, SlackAdapter)
        await adapter.close()


def _yaml_list(text: str, key: str) -> set[str]:
    """The items of a block list under `key:` in the manifest; no YAML parser is needed."""
    block = re.search(rf"^(\s*){re.escape(key)}:\n((?:\1\s+- .+\n)+)", text, re.MULTILINE)
    assert block is not None, f"the manifest has no {key} list"
    return {line.split("- ", 1)[1].strip().strip("\"'") for line in block[2].splitlines()}


def test_the_manifest_grants_exactly_the_scopes_and_events_used() -> None:
    text = MANIFEST.read_text(encoding="utf-8")
    assert _yaml_list(text, "bot") == BOT_SCOPES
    assert _yaml_list(text, "bot_events") == BOT_EVENTS
    assert "socket_mode_enabled: true" in text
    assert not re.search(r"^\s+user:", text, re.MULTILINE)  # no user-token scopes
    guide = (REPO_ROOT / "docs" / "guide" / "slack.md").read_text(encoding="utf-8")
    assert all(scope in guide for scope in APP_SCOPES | BOT_SCOPES)
