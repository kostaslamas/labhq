"""Chat channels: meetings mirrored to a chat service, owner replies read back."""

from labhq.chat.base import Channel, ChatAdapter, ChatError, Persona, Reply, Thread
from labhq.chat.bindings import BindingStore
from labhq.chat.registry import (
    ChatAdapterFactory,
    ChatContext,
    Registration,
    configured_chat_adapters,
)
from labhq.chat.text import split_message

__all__ = [
    "BindingStore",
    "Channel",
    "ChatAdapter",
    "ChatAdapterFactory",
    "ChatContext",
    "ChatError",
    "Persona",
    "Registration",
    "Reply",
    "Thread",
    "configured_chat_adapters",
    "split_message",
]
