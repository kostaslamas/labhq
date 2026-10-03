"""The Discord chat adapter: REST through httpx, the gateway through websockets."""

from labhq.chat.discord.adapter import DiscordAdapter
from labhq.chat.discord.settings import DiscordSettings

__all__ = ["DiscordAdapter", "DiscordSettings"]
