"""The agent card: this instance's CEO as one skill-bearing agent behind bearer auth."""

from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    HTTPAuthSecurityScheme,
    SecurityRequirement,
    SecurityScheme,
    StringList,
)

import labhq
from labhq.federation.keys import KEY_PREFIX

JSONRPC_BINDING = "JSONRPC"
# The protocol version the card speaks, and so the one the interface advertises.
PROTOCOL_VERSION = "1.0"
SCHEME_NAME = "federationKey"
TEXT_MODE = "text/plain"


def build_card(rpc_url: str) -> AgentCard:
    """The card for the JSON-RPC endpoint at `rpc_url`.

    Streaming, push notifications and the extended card are off on purpose: the upstream
    reads a task with `GetTask`, so a node never has to be dialled back.
    """
    return AgentCard(
        name="labhq CEO",
        description=(
            "The CEO of a labhq instance. Send it an order as text; it delegates inside its own "
            "projects and reports a status with a pointer to the result, never the work itself."
        ),
        version=labhq.__version__,
        supported_interfaces=[
            AgentInterface(
                url=rpc_url, protocol_binding=JSONRPC_BINDING, protocol_version=PROTOCOL_VERSION
            )
        ],
        capabilities=AgentCapabilities(
            streaming=False, push_notifications=False, extended_agent_card=False
        ),
        default_input_modes=[TEXT_MODE],
        default_output_modes=[TEXT_MODE],
        skills=[
            AgentSkill(
                id="take-order",
                name="Take an order",
                description=(
                    "Receive an order from an upstream manager, carry it out through this "
                    "instance's own team, and report progress, completion or a blocker."
                ),
                tags=["federation", "orders"],
                examples=["Add a dark mode toggle to the settings page."],
                input_modes=[TEXT_MODE],
                output_modes=[TEXT_MODE],
            )
        ],
        security_schemes={
            SCHEME_NAME: SecurityScheme(
                http_auth_security_scheme=HTTPAuthSecurityScheme(
                    scheme="Bearer",
                    bearer_format=f"{KEY_PREFIX}…",
                    description="The federation key `labhq federation invite` printed here.",
                )
            )
        },
        security_requirements=[SecurityRequirement(schemes={SCHEME_NAME: StringList()})],
    )
