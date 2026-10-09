"""Acceptance 1: B serves a valid agent card, checked against the SDK's own models."""

from a2a.client import A2ACardResolver
from a2a.types import AgentCard
from google.protobuf.json_format import ParseDict

from tests.federation.a2a.conftest import A2A_URL, NODE_URL, A2aPairing


async def test_the_card_parses_strictly_as_an_a2a_agent_card(a2a: A2aPairing) -> None:
    async with a2a.http() as client:  # no key: discovery is public
        response = await client.get("/api/federation/a2a/.well-known/agent-card.json")

    assert response.status_code == 200
    # Strict parse: an unknown or mistyped field would raise.
    card = ParseDict(response.json(), AgentCard())
    [interface] = card.supported_interfaces
    assert (interface.protocol_binding, interface.url) == ("JSONRPC", A2A_URL)
    assert interface.protocol_version == "1.0"
    assert card.name and card.description and card.version
    [skill] = card.skills
    assert skill.id == "take-order"
    assert card.capabilities.streaming is False
    assert card.capabilities.push_notifications is False


async def test_the_card_declares_bearer_auth_with_the_federation_key(a2a: A2aPairing) -> None:
    async with a2a.http() as client:
        resolver = A2ACardResolver(client, f"{NODE_URL}/api/federation/a2a")
        card = await resolver.get_agent_card()

    scheme = card.security_schemes["federationKey"].http_auth_security_scheme
    assert scheme.scheme == "Bearer"
    assert "lhqf_" in scheme.bearer_format
    [requirement] = card.security_requirements
    assert list(requirement.schemes) == ["federationKey"]
