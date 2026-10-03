"""The chat contract, run against the Slack adapter: Web API mocked, Socket Mode from fixtures."""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.chat.contract import CHECKS
from tests.chat.fake_discord import SteppedClock
from tests.chat.fake_slack import SlackHarness


@pytest.fixture
async def slack_harness(
    sessions: async_sessionmaker[AsyncSession], stepped_clock: SteppedClock
) -> AsyncIterator[SlackHarness]:
    harness = SlackHarness(sessions, stepped_clock)
    async with harness.client:
        yield harness


@pytest.mark.parametrize("check", sorted(CHECKS))
async def test_slack_honours_the_chat_contract(slack_harness: SlackHarness, check: str) -> None:
    await CHECKS[check](slack_harness)
