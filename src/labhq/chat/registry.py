"""`name -> factory` for chat adapters. A service without credentials is not registered."""

from collections.abc import Callable
from dataclasses import dataclass

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.approvals.registry import Registry
from labhq.chat.base import ChatAdapter
from labhq.chat.bindings import BindingStore
from labhq.chat.discord import DiscordAdapter, DiscordSettings
from labhq.clock import Clock


@dataclass(frozen=True)
class ChatContext:
    sessions: async_sessionmaker[AsyncSession]
    client: httpx.AsyncClient
    clock: Clock


type ChatAdapterFactory = Callable[[ChatContext], ChatAdapter]


@dataclass(frozen=True)
class Registration:
    name: str
    configured: Callable[[], bool]
    factory: ChatAdapterFactory


def _discord_configured() -> bool:
    return DiscordSettings().bot_token is not None


def _discord(context: ChatContext) -> ChatAdapter:
    return DiscordAdapter(
        settings=DiscordSettings(),
        store=BindingStore(context.sessions, "discord", clock=context.clock),
        client=context.client,
        clock=context.clock,
    )


# A new chat service is a new row here (Slack in Phase 5), never an edit to a caller.
REGISTRATIONS = (Registration("discord", _discord_configured, _discord),)


def configured_chat_adapters(
    registrations: tuple[Registration, ...] = REGISTRATIONS,
) -> Registry[ChatAdapterFactory]:
    """The adapters whose credentials are set. Empty is normal: meetings stay in the database."""
    registry = Registry[ChatAdapterFactory]("chat adapter")
    for registration in registrations:
        if registration.configured():
            registry.register(registration.name, registration.factory)
    return registry
