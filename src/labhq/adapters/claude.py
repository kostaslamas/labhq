"""The Claude Code adapter, on `ClaudeSDKClient`.

Every run starts the pinned Claude Code binary with no user or project settings, in the
task's worktree, with the caller's hooks. Behaviour it relies on was measured in
spikes/agent_sdk/RESULTS.md.
"""

import os
import shutil
from collections.abc import AsyncIterator, Callable, Mapping
from pathlib import Path
from typing import Any, Protocol, cast

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, ResultMessage
from claude_agent_sdk.types import PermissionMode
from pydantic import BaseModel, ConfigDict

from labhq.adapters.base import AdapterError, AdapterEvent, AdapterResult, RunRequest
from labhq.adapters.claude_env import child_environment
from labhq.adapters.claude_messages import to_event, to_result


class SDKClient(Protocol):
    """The part of `ClaudeSDKClient` the adapter uses; tests stub it here."""

    async def connect(self) -> None: ...

    async def query(self, prompt: str) -> None: ...

    def receive_response(self) -> AsyncIterator[Any]: ...

    async def interrupt(self) -> None: ...

    async def disconnect(self) -> None: ...


ClientFactory = Callable[[ClaudeAgentOptions], SDKClient]


class ClaudeAgentConfig(BaseModel):
    """The keys of `agents.config` this adapter reads; other keys belong to other modules."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    # Agents work unattended inside their worktree by default (plan §5, rule 1).
    permission_mode: PermissionMode = "bypassPermissions"
    model: str | None = None
    max_turns: int | None = None


def _default_client(options: ClaudeAgentOptions) -> SDKClient:
    return ClaudeSDKClient(options)


def default_cli_path(configured: Path | None) -> Path | None:
    # The wheel bundles a different Claude Code build; prefer the installed one.
    if configured is not None:
        return configured
    found = shutil.which("claude")
    return Path(found) if found else None


class ClaudeAdapter:
    def __init__(
        self,
        *,
        cli_path: Path | None,
        client_factory: ClientFactory = _default_client,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._cli_path = cli_path
        self._client_factory = client_factory
        self._environ = environ if environ is not None else os.environ
        self._client: SDKClient | None = None
        self._result: AdapterResult | None = None
        self._model: str | None = None

    def options_for(self, request: RunRequest) -> ClaudeAgentOptions:
        config = ClaudeAgentConfig.model_validate(dict(request.config))
        return ClaudeAgentOptions(
            cli_path=self._cli_path,
            # No user, project or local settings: their hooks and rules must not leak in.
            setting_sources=[],
            cwd=request.cwd,
            permission_mode=config.permission_mode,
            model=config.model,
            max_turns=config.max_turns,
            resume=request.resume_session_id,
            hooks=cast(Any, dict(request.hooks)) if request.hooks else None,
            env=child_environment(self._environ),
        )

    async def start(self, request: RunRequest) -> None:
        if self._client is not None:
            raise AdapterError("an adapter instance serves one run")
        self._client = self._client_factory(self.options_for(request))
        await self._client.connect()
        await self._client.query(request.prompt)

    async def events(self) -> AsyncIterator[AdapterEvent]:
        client = self._connected()
        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                self._model = message.model
            if isinstance(message, ResultMessage):
                self._result = to_result(message, self._model)
            yield to_event(message)
        if self._result is None:
            raise AdapterError("the stream ended without a result message")

    async def send(self, text: str) -> None:
        # Streaming input: the message joins the running conversation.
        await self._connected().query(text)

    async def interrupt(self) -> None:
        await self._connected().interrupt()

    def result(self) -> AdapterResult:
        if self._result is None:
            raise AdapterError("the run has no result yet")
        return self._result

    async def close(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            await client.disconnect()

    def _connected(self) -> SDKClient:
        if self._client is None:
            raise AdapterError("start() was not called")
        return self._client
