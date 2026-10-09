"""`kind -> definition`: what a channel needs and how it becomes a notifier.

A new channel kind is a new registration here, never an edit to the store, the API or the
fan-out. Fields marked `secret` go to the owner-only secret file; the rest to the database.
"""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.approvals.registry import Registry
from labhq.channels.chat import ChatNotifier
from labhq.chat.registry import ChatAdapterFactory, ChatContext
from labhq.clock import Clock
from labhq.notify.base import Notifier, NotifyError
from labhq.notify.ntfy import NtfyNotifier
from labhq.notify.settings import NotifySettings
from labhq.notify.telegram import TelegramNotifier

FIELD_MAX_CHARS = 200


class ChannelConfigError(ValueError):
    """The submitted settings are not valid. The message never repeats a secret."""


@dataclass(frozen=True)
class ChannelField:
    name: str
    label: str
    secret: bool = False
    # A full-match pattern; the error says which field failed, not what was typed.
    pattern: str = r"[^\s]+"
    default: str | None = None


@dataclass(frozen=True)
class BuildContext:
    config: Mapping[str, str]
    secrets: Mapping[str, str]
    client: httpx.AsyncClient
    sessions: async_sessionmaker[AsyncSession]
    clock: Clock
    settings: NotifySettings
    data_dir: Path
    # The chat services with credentials; empty is normal.
    chat: Registry[ChatAdapterFactory]


type ChannelBuilder = Callable[[BuildContext], Notifier]


@dataclass(frozen=True)
class ChannelKind:
    name: str
    label: str
    fields: tuple[ChannelField, ...]
    build: ChannelBuilder

    def split(self, values: Mapping[str, str]) -> tuple[dict[str, str], dict[str, str]]:
        """Validated `(config, secrets)`; unknown fields are refused, defaults filled in."""
        known = {field.name: field for field in self.fields}
        extra = sorted(set(values) - set(known))
        if extra:
            raise ChannelConfigError(f"{self.name} has no field {extra[0]!r}")
        config: dict[str, str] = {}
        secrets: dict[str, str] = {}
        for field in self.fields:
            value = (values.get(field.name) or field.default or "").strip()
            if not value:
                raise ChannelConfigError(f"{self.name} needs {field.label}")
            if len(value) > FIELD_MAX_CHARS or not re.fullmatch(field.pattern, value):
                raise ChannelConfigError(f"{field.label} is not valid")
            (secrets if field.secret else config)[field.name] = value
        return config, secrets


def _ntfy(context: BuildContext) -> Notifier:
    return NtfyNotifier(
        context.client,
        server=context.config["server"],
        topic=context.config["topic"],
        priority=context.settings.ntfy_priority,
    )


def _telegram(context: BuildContext) -> Notifier:
    return TelegramNotifier(
        context.client, token=context.secrets["token"], chat_id=context.config["chat_id"]
    )


def _chat(service: str) -> ChannelBuilder:
    def build(context: BuildContext) -> Notifier:
        if service not in context.chat:
            raise NotifyError(f"{service} is not set up on this machine")
        adapter = context.chat.get(service)(
            ChatContext(context.sessions, context.client, context.clock)
        )
        return ChatNotifier(adapter)

    return build


channel_kinds: Registry[ChannelKind] = Registry("channel kind")
channel_kinds.register(
    "ntfy",
    ChannelKind(
        "ntfy",
        "ntfy",
        (
            ChannelField(
                "server", "the ntfy server", pattern=r"https?://[^\s]+", default="https://ntfy.sh"
            ),
            ChannelField("topic", "the topic", pattern=r"[A-Za-z0-9_-]{1,64}"),
        ),
        _ntfy,
    ),
)
channel_kinds.register(
    "telegram",
    ChannelKind(
        "telegram",
        "Telegram",
        (
            ChannelField("chat_id", "the chat id", pattern=r"-?\d{1,20}|@[A-Za-z0-9_]{3,64}"),
            ChannelField("token", "the bot token", secret=True),
        ),
        _telegram,
    ),
)
# The bot token of a chat service is set up by its own onboarding step, not here.
channel_kinds.register("discord", ChannelKind("discord", "Discord", (), _chat("discord")))
channel_kinds.register("slack", ChannelKind("slack", "Slack", (), _chat("slack")))
