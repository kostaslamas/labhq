"""The chat contract, run against the fake and the Discord adapter alike."""

import pytest

from labhq.chat import Reply
from labhq.chat.contract import (
    CHECKS,
    ChatHarness,
    ContractViolationError,
    Speaker,
    check_only_owner_replies_in_labhq_threads,
)
from labhq.chat.fake import FakeChatAdapter


@pytest.mark.parametrize("check", sorted(CHECKS))
async def test_adapter_honours_the_chat_contract(harness: ChatHarness, check: str) -> None:
    await CHECKS[check](harness)


class _EchoingAdapter(FakeChatAdapter):
    """Yields every inbound message, as a mirror that echoes itself would."""

    async def replies(self):  # type: ignore[no-untyped-def]
        while (message := await self._next_inbound()) is not None:
            thread = await self._store.labhq_thread(message.channel_id)
            if thread is not None:
                yield Reply(thread, message.author, message.text, "ref")


async def test_the_contract_rejects_an_adapter_that_echoes_bots(fake_harness) -> None:
    async def make() -> FakeChatAdapter:
        plain = await type(fake_harness).make(fake_harness)
        assert isinstance(plain, FakeChatAdapter)
        return _EchoingAdapter(fake_harness.service, plain._store)

    fake_harness.make = make
    with pytest.raises(ContractViolationError, match="from bot"):
        await check_only_owner_replies_in_labhq_threads(fake_harness)


def test_speakers_cover_every_kind_the_issue_names() -> None:
    assert set(Speaker) == {"owner", "other_user", "bot", "webhook"}
