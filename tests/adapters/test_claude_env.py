"""ADR 0001: no credential reaches the Claude Code child except `ANTHROPIC_API_KEY`, if set.

The SDK merges `options.env` over the parent's whole environment when it spawns the CLI,
so these tests capture the environment at the spawn itself, not the overlay alone.
"""

import os
from typing import Any

import claude_agent_sdk._internal.transport.subprocess_cli as sdk_transport
import pytest

from labhq.adapters import ClaudeAdapter, RunRequest
from labhq.adapters.claude_env import child_environment, is_inherited
from tests.adapters.stub_sdk import CLI_PATH

UNRELATED_SECRETS = {
    "LABHQ_TEST_SERVICE_TOKEN": "not-for-children",
    "LABHQ_TEST_DB_PASSWORD": "hunter2",
    "LABHQ_TEST_CLOUD_SECRET": "s3cr3t",
}


class _SpawnedError(Exception):
    pass


async def _spawned_environment(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Start the adapter on the real SDK transport and return the env it spawns with."""
    captured: dict[str, str] = {}

    async def open_process(cmd: list[str], **kwargs: Any) -> Any:
        captured.update(kwargs["env"])
        raise _SpawnedError

    monkeypatch.setenv("CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK", "1")
    monkeypatch.setattr(sdk_transport.anyio, "open_process", open_process)
    adapter = ClaudeAdapter(cli_path=CLI_PATH)
    with pytest.raises(Exception, match="Failed to start Claude Code"):
        await adapter.start(RunRequest(prompt="hello"))
    assert captured, "the spawn was never reached"
    return {name: value for name, value in captured.items() if value != ""}


@pytest.fixture
def secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in UNRELATED_SECRETS.items():
        monkeypatch.setenv(name, value)


@pytest.mark.usefixtures("secrets")
async def test_child_gets_the_api_key_when_it_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-only")
    env = await _spawned_environment(monkeypatch)
    assert env["ANTHROPIC_API_KEY"] == "sk-test-only"
    assert not set(UNRELATED_SECRETS) & set(env)


@pytest.mark.usefixtures("secrets")
async def test_child_gets_no_api_key_when_it_is_not_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    env = await _spawned_environment(monkeypatch)
    assert "ANTHROPIC_API_KEY" not in env
    assert not set(UNRELATED_SECRETS) & set(env)


@pytest.mark.usefixtures("secrets")
async def test_child_sees_only_allowlisted_inherited_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-only")
    env = await _spawned_environment(monkeypatch)
    # Names the SDK adds for the child are not in the parent; everything else came from it.
    inherited = {name for name in env if name in os.environ}
    leaked = {name for name in inherited if not is_inherited(name)} - {"ANTHROPIC_API_KEY"}
    assert leaked == set()


def test_overlay_blanks_everything_outside_the_allowlist() -> None:
    environ = {"PATH": "/usr/bin", "HOME": "/home/me", "LC_ALL": "C", **UNRELATED_SECRETS}
    overlay = child_environment(environ)
    assert overlay == dict.fromkeys(UNRELATED_SECRETS, "")


def test_an_empty_api_key_counts_as_unset() -> None:
    assert child_environment({"ANTHROPIC_API_KEY": ""}) == {}
