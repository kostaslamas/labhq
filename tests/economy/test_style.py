"""Output style per recipient: a registry fed by agent config (plan §7.1)."""

import pytest

from labhq.economy.style import (
    AGENT_STYLE,
    RECIPIENT_CONFIG_KEY,
    USER_STYLE,
    DuplicateRecipientError,
    StyleRegistry,
    UnknownRecipientError,
    default_registry,
    recipient_from_config,
    styled_system_prompt,
)

ROLE_PROMPT = "You are the backend worker for project alpha."


def test_defaults_are_terse_for_agents_and_natural_for_the_user() -> None:
    registry = default_registry()
    assert registry.recipients() == {"agent", "user"}
    assert registry.get("agent").instruction == AGENT_STYLE
    assert registry.get("user").instruction == USER_STYLE
    assert "terse" in AGENT_STYLE
    assert "natural" in USER_STYLE


@pytest.mark.parametrize("recipient", ["agent", "user"])
def test_the_style_limits_prose_not_reasoning_or_code(recipient: str) -> None:
    instruction = default_registry().get(recipient).instruction
    assert "prose only" in instruction
    assert "never shorten code" in instruction


@pytest.mark.parametrize(
    ("config", "expected"),
    [({RECIPIENT_CONFIG_KEY: "user"}, USER_STYLE), ({RECIPIENT_CONFIG_KEY: "agent"}, AGENT_STYLE)],
)
def test_the_recipient_comes_from_agent_config(config: dict[str, str], expected: str) -> None:
    prompt = styled_system_prompt(ROLE_PROMPT, config, default_registry())
    assert prompt == f"{ROLE_PROMPT}\n\n{expected}"


def test_a_role_without_a_recipient_writes_for_agents() -> None:
    assert recipient_from_config({}) == "agent"
    assert styled_system_prompt(ROLE_PROMPT, {}, default_registry()).endswith(AGENT_STYLE)


def test_an_empty_role_prompt_gets_the_style_alone() -> None:
    assert styled_system_prompt("  ", {}, default_registry()) == AGENT_STYLE


def test_a_new_recipient_is_a_new_registration() -> None:
    registry = default_registry()
    registry.register("meeting", "Output style: one line per point.")
    prompt = styled_system_prompt(ROLE_PROMPT, {RECIPIENT_CONFIG_KEY: "meeting"}, registry)
    assert prompt.endswith("Output style: one line per point.")
    # The existing recipients are untouched by the new registration.
    assert registry.get("agent").instruction == AGENT_STYLE


def test_an_unregistered_recipient_is_an_error_not_a_silent_default() -> None:
    with pytest.raises(UnknownRecipientError):
        styled_system_prompt(ROLE_PROMPT, {RECIPIENT_CONFIG_KEY: "nobody"}, default_registry())


def test_registering_twice_needs_an_explicit_replace() -> None:
    registry = default_registry()
    with pytest.raises(DuplicateRecipientError):
        registry.register("agent", "Something else.")
    registry.register("agent", "Something else.", replace=True)
    assert registry.get("agent").instruction == "Something else."


@pytest.mark.parametrize(("recipient", "instruction"), [("", "x"), ("agent", "  ")])
def test_a_style_needs_a_recipient_and_an_instruction(recipient: str, instruction: str) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        StyleRegistry().register(recipient, instruction)


@pytest.mark.parametrize("value", ["", 3, None])
def test_a_malformed_recipient_in_config_is_rejected(value: object) -> None:
    with pytest.raises(ValueError, match=RECIPIENT_CONFIG_KEY):
        recipient_from_config({RECIPIENT_CONFIG_KEY: value})
