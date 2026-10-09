"""Agent kinds by name: the SDK's Claude Code plus every tmux kind, with where each runs."""

from dataclasses import replace

import pytest

from labhq.adapters.kinds import (
    CLAUDE_SDK,
    UnknownAgentChoiceError,
    agent_choices,
    choice_named,
    tmux_choices,
)
from labhq.adapters.tmux.agents import CODEX, AgentKinds, default_kinds


def test_every_registered_tmux_kind_is_a_choice_with_a_display_name() -> None:
    names = [choice.name for choice in agent_choices()]

    assert names == ["claude", *default_kinds.names()]
    assert all(choice.display_name for choice in agent_choices())


def test_a_tmux_kind_names_the_tmux_adapter_and_its_own_config() -> None:
    choice = choice_named("codex")

    assert choice.adapter == "tmux"
    assert dict(choice.config) == {"agent": "codex"}
    assert choice.binary == "codex"
    assert choice.display_name == "Codex"


def test_the_sdk_claude_runs_on_the_claude_adapter() -> None:
    assert (CLAUDE_SDK.adapter, dict(CLAUDE_SDK.config)) == ("claude", {})


def test_a_new_registration_becomes_a_choice_without_other_edits() -> None:
    kinds: AgentKinds = default_kinds.copy()
    kinds.register(replace(CODEX, name="other", display_name=""))

    other = next(choice for choice in tmux_choices(kinds) if choice.name == "other")

    assert other.display_name == "other"
    assert choice_named("other", kinds).config["agent"] == "other"


def test_availability_follows_the_binary_on_the_path() -> None:
    choice = choice_named("codex")

    assert choice.found(lambda binary: f"/bin/{binary}") == "/bin/codex"
    assert choice.found(lambda binary: None) is None


def test_an_unknown_kind_lists_the_valid_ones() -> None:
    with pytest.raises(UnknownAgentChoiceError) as error:
        choice_named("nope")

    assert "valid kinds: claude, aider, claude-code, codex, cursor-agent, gemini, opencode" in str(
        error.value
    )
