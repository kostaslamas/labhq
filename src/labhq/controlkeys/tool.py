"""`send_control_key`: the one key an agent may send to a direct report (`escape`)."""

from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from labhq.agenttools import AgentToolSpec, ToolContext
from labhq.controlkeys.service import (
    AGENT_SENDER_ROLES,
    ControlKeyError,
    ControlKeyService,
    agent_sender,
)

type ServiceFactory = Callable[[ToolContext], ControlKeyService]


class SendControlKey(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent: int = Field(description="A direct report, by id.")
    key: Literal["escape"] = Field(description="Escape stops the report's current turn.")


def control_key_tools(service: ServiceFactory) -> list[AgentToolSpec]:
    async def send_control_key(context: ToolContext, arguments: SendControlKey) -> str:
        try:
            # The sender is the run's agent, never an argument.
            await service(context).send(agent_sender(context.agent_id), arguments.agent, "escape")
        except ControlKeyError as error:
            return f"Refused: {error}"
        return f"Sent escape to agent {arguments.agent}."

    return [
        AgentToolSpec(
            name="send_control_key",
            description=(
                "Press Escape in a direct report's terminal to stop its current turn. "
                "Other keys and other agents are refused."
            ),
            input_model=SendControlKey,
            roles=AGENT_SENDER_ROLES,
            read_only=False,
            handler=send_control_key,
        )
    ]
