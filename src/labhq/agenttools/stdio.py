"""`labhq mcp agent --run <id>`: a run agent's tools over stdio, for CLIs other than the SDK's.

The CLI starts this as its child process. Nothing listens on a port, and the server offers
the same tools the SDK adapter serves in process, bound to the agent of the run.
"""

from collections.abc import Sequence
from typing import Any

import mcp_types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.adapters import AgentTool
from labhq.agenttools.registry import AgentToolRegistry, ToolContext, tools_for
from labhq.clock import Clock
from labhq.db.models import Agent, Run

SERVER_NAME = "labhq-agent"


def _text(text: str, *, error: bool = False) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)], is_error=error)


def build_server(tools: Sequence[AgentTool]) -> Server[Any]:
    by_name = {tool.name: tool for tool in tools}
    listed = [
        types.Tool(
            name=tool.name,
            description=tool.description,
            input_schema=tool.input_schema,
            annotations=types.ToolAnnotations(read_only_hint=tool.read_only),
        )
        for tool in tools
    ]

    async def list_tools(
        context: Any, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=listed)

    async def call_tool(context: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        tool = by_name.get(params.name)
        if tool is None:
            return _text(f"There is no tool {params.name!r} for this agent.", error=True)
        return _text(await tool.handler(dict(params.arguments or {})))

    return Server(SERVER_NAME, on_list_tools=list_tools, on_call_tool=call_tool)


async def run_tools(
    registry: AgentToolRegistry,
    sessions: async_sessionmaker[AsyncSession],
    clock: Clock,
    run_id: int,
) -> list[AgentTool]:
    """The tools of the run's agent, bound to that agent. The caller never names the agent."""
    async with sessions() as db:
        run = await db.get(Run, run_id)
        if run is None:
            raise LookupError(f"there is no run {run_id}")
        agent = await db.get_one(Agent, run.agent_id)
    context = ToolContext(agent_id=agent.id, run_id=run.id, sessions=sessions, clock=clock)
    return tools_for(registry, agent, context)


async def serve_stdio(tools: Sequence[AgentTool]) -> None:
    server = build_server(tools)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
