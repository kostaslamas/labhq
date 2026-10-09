"""The Call Center answers 'send me Telegram too' with a link, and never asks for a secret."""

from collections.abc import Iterator

import pytest

import labhq.mcp.tools  # noqa: F401  (registers every tool)
from labhq.api.public_url import announce_exposure
from labhq.mcp.tools.channels import channel_setup_tool
from labhq.mcp.tools.registry import default_registry


@pytest.fixture(autouse=True)
def no_exposure() -> Iterator[None]:
    announce_exposure(None)
    yield
    announce_exposure(None)


async def test_the_answer_is_the_link_to_the_channels_page() -> None:
    announce_exposure("https://labhq.example.org/")

    answer = await channel_setup_tool("telegram")

    assert "Telegram" in answer
    assert "https://labhq.example.org/channels" in answer


async def test_without_a_public_address_it_names_the_page_and_says_why_there_is_no_link() -> None:
    answer = await channel_setup_tool()

    assert "/channels" in answer and "https://" not in answer


async def test_an_unknown_kind_still_gets_the_page() -> None:
    announce_exposure("https://labhq.example.org")

    assert "https://labhq.example.org/channels" in await channel_setup_tool("pigeon")


def test_the_tool_tells_the_model_never_to_ask_for_a_secret() -> None:
    spec = next(spec for spec in default_registry if spec.name == "channel_setup")

    assert "Never ask the owner for a token" in spec.description
    assert spec.annotations is not None and spec.annotations.read_only_hint is True
