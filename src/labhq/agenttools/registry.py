"""Engine tools for working agents, as data: a new tool is a new registration.

A tool acts as the agent whose run it serves. That agent is bound when the tool is, from the
run, so no argument the model writes can make a tool act for another agent.
"""

from collections.abc import Awaitable, Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.adapters import AgentTool
from labhq.clock import Clock
from labhq.db.models import Agent
from labhq.guards.readonly import is_read_only

# A tool whose roles hold this is given to every agent.
EVERY_ROLE = "*"
# `agents.config["tools"]`: tool names an agent gets on top of its role's.
TOOLS_CONFIG_KEY = "tools"


@dataclass(frozen=True)
class ToolContext:
    """Who is calling, taken from the run. Handlers read the agent from here, never from input."""

    agent_id: int
    run_id: int | None
    sessions: async_sessionmaker[AsyncSession]
    clock: Clock


type ToolHandler = Callable[[ToolContext, Any], Awaitable[str]]


@dataclass(frozen=True)
class AgentToolSpec:
    name: str
    description: str
    # Validates the model's arguments; its JSON schema is what the agent sees.
    input_model: type[BaseModel]
    roles: frozenset[str]
    read_only: bool
    # Called with the bound context and a validated `input_model` instance.
    handler: ToolHandler


class UnknownAgentToolError(LookupError):
    pass


class AgentToolRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, AgentToolSpec] = {}

    def register(self, spec: AgentToolSpec, *, replace: bool = False) -> None:
        if spec.name in self._specs and not replace:
            raise ValueError(f"agent tool {spec.name!r} is already registered")
        self._specs[spec.name] = spec

    def __iter__(self) -> Iterator[AgentToolSpec]:
        return iter(self._specs.values())

    def copy(self) -> "AgentToolRegistry":
        clone = AgentToolRegistry()
        clone._specs = dict(self._specs)
        return clone

    def for_agent(self, role: str, config: Mapping[str, Any]) -> list[AgentToolSpec]:
        """The tools of `role`, plus those named in the agent's config.

        A read-only agent gets the read-only ones only, whatever its config names.
        """
        named = _named_tools(config)
        unknown = sorted(named - self._specs.keys())
        if unknown:
            raise UnknownAgentToolError(f"unknown agent tools in config: {', '.join(unknown)}")
        chosen = [
            spec
            for spec in self._specs.values()
            if spec.name in named or role in spec.roles or EVERY_ROLE in spec.roles
        ]
        if is_read_only(config):
            return [spec for spec in chosen if spec.read_only]
        return chosen


def _named_tools(config: Mapping[str, Any]) -> frozenset[str]:
    names = config.get(TOOLS_CONFIG_KEY, [])
    if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
        raise ValueError(f"{TOOLS_CONFIG_KEY} must be a list of tool names: {names!r}")
    return frozenset(names)


def bind(spec: AgentToolSpec, context: ToolContext) -> AgentTool:
    """The tool as an adapter serves it, acting for `context.agent_id` only."""

    async def handler(arguments: dict[str, Any]) -> str:
        try:
            parsed = spec.input_model.model_validate(arguments)
        except ValidationError as error:
            # The model reads this and can retry; it is not a failure of the run.
            return f"Invalid arguments for {spec.name}: {error.errors(include_url=False)}"
        return await spec.handler(context, parsed)

    return AgentTool(
        name=spec.name,
        description=spec.description,
        input_schema=spec.input_model.model_json_schema(),
        handler=handler,
        read_only=spec.read_only,
    )


def tools_for(registry: AgentToolRegistry, agent: Agent, context: ToolContext) -> list[AgentTool]:
    return [bind(spec, context) for spec in registry.for_agent(agent.role, agent.config)]
