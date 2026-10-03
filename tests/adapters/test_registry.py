"""The registry maps adapter keys to factories; adding one touches nothing else."""

import pytest

from labhq.adapters import (
    AdapterRegistry,
    ClaudeAdapter,
    FakeAdapter,
    OllamaAdapter,
    UnknownAdapterError,
    default_registry,
)


def test_built_in_adapters_are_registered() -> None:
    assert default_registry.adapter_keys() == ["claude", "fake", "ollama"]
    assert isinstance(default_registry.create("fake"), FakeAdapter)
    assert isinstance(default_registry.create("claude"), ClaudeAdapter)
    assert isinstance(default_registry.create("ollama"), OllamaAdapter)


def test_each_create_builds_a_new_instance() -> None:
    assert default_registry.create("fake") is not default_registry.create("fake")


def test_an_unknown_key_is_an_error() -> None:
    with pytest.raises(UnknownAdapterError, match="codex"):
        AdapterRegistry().create("codex")


def test_a_key_cannot_be_taken_twice_by_accident() -> None:
    registry = AdapterRegistry()
    registry.register("fake", FakeAdapter)
    with pytest.raises(ValueError, match="already registered"):
        registry.register("fake", FakeAdapter)
    registry.register("fake", FakeAdapter, replace=True)


def test_a_copy_does_not_change_the_original() -> None:
    clone = default_registry.copy()
    clone.register("dummy", FakeAdapter)
    assert "dummy" not in default_registry.adapter_keys()
    assert "dummy" in clone.adapter_keys()
