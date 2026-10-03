"""Who a post appears to come from: an agent's persona, the owner or labhq itself.

An agent's persona is `agents.config["persona"]` (`name`, `avatar_url`); whatever it leaves
out is generated, so every agent writes under its own name and face with no setup.
"""

from typing import Any

from labhq.chat import Persona
from labhq.db.models import Agent
from labhq.meetings.channels.settings import ChannelSettings

PERSONA_CONFIG_KEY = "persona"


def agent_persona(agent: Agent, settings: ChannelSettings) -> Persona:
    configured: Any = agent.config.get(PERSONA_CONFIG_KEY)
    override = configured if isinstance(configured, dict) else {}
    name = override.get("name") or f"{agent.title} ({agent.role})"
    avatar = override.get("avatar_url") or _generated_avatar(agent.id, settings)
    return Persona(str(name), str(avatar) if avatar else None)


def system_persona(settings: ChannelSettings) -> Persona:
    return Persona(settings.system_name)


def _generated_avatar(agent_id: int, settings: ChannelSettings) -> str | None:
    if not settings.avatar_url_template:
        return None
    # The seed is the id alone: an agent's title never leaves labhq through an avatar URL.
    return settings.avatar_url_template.format(seed=f"labhq-agent-{agent_id}")
