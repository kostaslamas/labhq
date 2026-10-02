"""Token economy: output style per recipient, structured handoffs and the `rtk` hook."""

from labhq.economy.handoff import Handoff, render_handoff
from labhq.economy.rtk import RtkHook, RunWarning, rtk_hook
from labhq.economy.style import (
    OutputStyle,
    StyleRegistry,
    default_registry,
    recipient_from_config,
    styled_system_prompt,
)

__all__ = [
    "Handoff",
    "OutputStyle",
    "RtkHook",
    "RunWarning",
    "StyleRegistry",
    "default_registry",
    "recipient_from_config",
    "render_handoff",
    "rtk_hook",
    "styled_system_prompt",
]
