"""The chat adapter contract: channels, threads, persona posts out, owner replies in."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol


class ChatError(RuntimeError):
    """A chat service refused or failed. The message must never carry a credential."""


@dataclass(frozen=True)
class Persona:
    """Who a post appears to come from: an agent's display name and avatar."""

    name: str
    avatar_url: str | None = None


@dataclass(frozen=True)
class Channel:
    key: str
    id: str


@dataclass(frozen=True)
class Thread:
    channel: Channel
    id: str


@dataclass(frozen=True)
class Reply:
    """An inbound message from the owner inside a labhq thread."""

    thread: Thread
    author: str
    text: str
    ref: str


class ChatAdapter(Protocol):
    # The service's message length limit; longer posts arrive as several messages.
    max_message_length: int

    async def ensure_channel(self, key: str, name: str) -> Channel:
        """The channel for `key`, created on first use and found again afterwards."""
        ...

    async def open_thread(self, channel: Channel, title: str) -> Thread: ...

    async def post(self, thread: Thread, persona: Persona, text: str) -> list[str]:
        """Post `text` as `persona`; returns the message refs, one per part, in order."""
        ...

    def replies(self) -> AsyncIterator[Reply]:
        """Owner messages in labhq threads, until `close`."""
        ...

    async def close(self) -> None: ...
