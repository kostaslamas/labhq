"""Ask the Call Center for another notification channel: the answer is a link, never a form."""

from mcp.types import ToolAnnotations

from labhq.api.public_url import current_public_url
from labhq.channels import channel_kinds, copy
from labhq.mcp.tools.registry import ToolSpec, default_registry

CHANNELS_PATH = "/channels"
SETUP = ToolAnnotations(readOnlyHint=True)


async def channel_setup_tool(kind: str | None = None) -> str:
    chosen = (kind or "").strip().lower()
    label = channel_kinds.get(chosen).label if chosen in channel_kinds else "ειδοποιήσεων"
    base = current_public_url()
    if base is None:
        return copy.SETUP_NO_LINK.format(kind=label)
    return copy.SETUP_LINK.format(kind=label, link=f"{base}{CHANNELS_PATH}")


default_registry.register(
    ToolSpec(
        "channel_setup",
        "Give the owner the link to the Channels page, where they add a notification channel "
        "(ntfy, telegram, discord or slack) with their passkey. Use it when the owner asks to "
        "be notified somewhere else, for example 'send me Telegram too'. kind is the channel "
        "the owner named, or leave it out. Never ask the owner for a token, a password or a "
        "code by voice or chat: the page collects them, and a channel is live once its test "
        "message arrives. Read the answer aloud as it is.",
        SETUP,
        channel_setup_tool,
    )
)
