"""The notifier contract: one message out, or a `NotifyError` the dispatcher can retry."""

from dataclasses import dataclass
from typing import Protocol


class NotifyError(RuntimeError):
    """A send failed. The message is stored on the outbox row, so it must never carry a secret."""


@dataclass(frozen=True)
class Message:
    title: str
    body: str
    click_url: str | None = None


class Notifier(Protocol):
    async def send(self, message: Message) -> None: ...
