"""The Claude Code adapter, on `ClaudeSDKClient`.

Every run starts the pinned Claude Code binary with no user or project settings, in the
task's worktree, with the caller's hooks. Behaviour it relies on was measured in
spikes/agent_sdk/RESULTS.md.
"""

import os
import shutil
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal, Protocol, cast

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    SdkMcpTool,
    create_sdk_mcp_server,
)
from claude_agent_sdk.types import McpServerConfig, PermissionMode, SystemPromptPreset
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict

from labhq.adapters.base import AdapterError, AdapterEvent, AdapterResult, AgentTool, RunRequest
from labhq.adapters.claude_env import child_environment
from labhq.adapters.claude_messages import to_event, to_result
from labhq.adapters.claude_model import model_options
from labhq.guards.readonly import READ_ONLY_MODE, read_only_matcher, read_only_permissions


class SDKClient(Protocol):
    """The part of `ClaudeSDKClient` the adapter uses; tests stub it here."""

    async def connect(self) -> None: ...

    async def query(self, prompt: str) -> None: ...

    def receive_response(self) -> AsyncIterator[Any]: ...

    async def interrupt(self) -> None: ...

    async def disconnect(self) -> None: ...


ClientFactory = Callable[[ClaudeAgentOptions], SDKClient]

# The in-process server that carries a run's own tools; its tools are `mcp__labhq__<name>`.
TOOL_SERVER = "labhq"


class ClaudeAgentConfig(BaseModel):
    """The keys of `agents.config` this adapter reads; other keys belong to other modules."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    # Agents work unattended inside their worktree by default (plan §5, rule 1); agents that
    # touch machines run read-only instead (plan §5, rule 2).
    permission_mode: PermissionMode | Literal["read_only"] = "bypassPermissions"
    model: str | None = None
    # Legacy extended thinking and raw CLI flags; `model_options` strips what a model rejects.
    max_thinking_tokens: int | None = None
    extra_args: dict[str, str | None] = {}
    max_turns: int | None = None
    # `[]` runs with no tools at all, as the usage extractor does (ADR 0003).
    tools: list[str] | None = None


def _default_client(options: ClaudeAgentOptions) -> SDKClient:
    return ClaudeSDKClient(options)


def default_cli_path(configured: Path | None) -> Path | None:
    # The wheel bundles a different Claude Code build; prefer the installed one.
    if configured is not None:
        return configured
    found = shutil.which("claude")
    return Path(found) if found else None


def _sdk_tool(spec: AgentTool) -> SdkMcpTool[Any]:
    async def handler(arguments: dict[str, Any]) -> dict[str, Any]:
        return {"content": [{"type": "text", "text": await spec.handler(arguments)}]}

    return SdkMcpTool(
        name=spec.name,
        description=spec.description,
        input_schema=spec.input_schema,
        handler=handler,
        annotations=ToolAnnotations(readOnlyHint=spec.read_only),
    )


def served_name(spec: AgentTool) -> str:
    return f"mcp__{TOOL_SERVER}__{spec.name}"


def tool_options(tools: Sequence[AgentTool], added: Sequence[AgentTool] = ()) -> dict[str, Any]:
    """Options that serve `tools` and `added` in this process.

    `tools` replace the built-in tools; `added` join them.
    """
    served = [*tools, *added]
    if not served:
        return {}
    server = create_sdk_mcp_server(TOOL_SERVER, tools=[_sdk_tool(spec) for spec in served])
    servers: dict[str, McpServerConfig] = {TOOL_SERVER: server}
    options: dict[str, Any] = {
        "mcp_servers": servers,
        # Only this server: no MCP configuration from the machine joins in.
        "strict_mcp_config": True,
        "allowed_tools": [served_name(spec) for spec in served],
    }
    if tools:
        # An empty list removes every built-in tool: no shell, no file reads or writes.
        options["tools"] = []
    return options


def system_prompt(append: str | None) -> SystemPromptPreset | None:
    # None keeps the adapter's previous behaviour; an append rides on Claude Code's preset.
    if append is None:
        return None
    return {"type": "preset", "preset": "claude_code", "append": append}


def read_only_options(request: RunRequest) -> dict[str, Any]:
    """Two layers: a Bash hook that classifies commands, and `can_use_tool` for the rest.

    `bypassPermissions` would skip `can_use_tool`, so the mode is `default`. Only read-only
    engine tools are served, and only they are pre-approved.
    """
    hooks: dict[str, list[Any]] = {key: list(value) for key, value in (request.hooks or {}).items()}
    hooks.setdefault("PreToolUse", []).append(read_only_matcher())
    tools = [spec for spec in request.tools if spec.read_only]
    added = [spec for spec in request.agent_tools if spec.read_only]
    return {
        "permission_mode": "default",
        "hooks": hooks,
        "can_use_tool": read_only_permissions(served_name(spec) for spec in [*tools, *added]),
        **tool_options(tools, added),
    }


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
        if config.permission_mode == READ_ONLY_MODE:
            mode_options = read_only_options(request)
        else:
            mode_options = {
                "permission_mode": config.permission_mode,
                "hooks": cast(Any, dict(request.hooks)) if request.hooks else None,
                **tool_options(request.tools, request.agent_tools),
            }
        # A resolved model wins; an agent that was run without the policy keeps its own.
        chosen, extra_env = model_options(
            request.model or config.model,
            effort=request.effort,
            max_output_tokens=request.max_output_tokens,
            max_thinking_tokens=config.max_thinking_tokens,
            extra_args=config.extra_args,
        )
        return ClaudeAgentOptions(
            cli_path=self._cli_path,
            # No user, project or local settings: their hooks and rules must not leak in.
            setting_sources=[],
            cwd=request.cwd,
            max_turns=config.max_turns,
            resume=request.resume_session_id,
            system_prompt=system_prompt(request.system_prompt_append),
            env={**child_environment(self._environ), **extra_env},
            **chosen,
            # A run's own tools replace the configured set; otherwise the config decides.
            **{"tools": config.tools, **mode_options},
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
