"""Read-only tools: what happened, what waits for the owner, how the machines are."""

from mcp.types import ToolAnnotations

from labhq.callcenter.answers import brief, health, inbox
from labhq.mcp.tools.registry import ToolSpec, default_registry
from labhq.mcp.tools.runtime import CLOCK, tool_session

READ_ONLY = ToolAnnotations(readOnlyHint=True)


async def brief_tool() -> str:
    async with tool_session() as db:
        return await brief(db, CLOCK)


async def inbox_tool() -> str:
    async with tool_session() as db:
        return await inbox(db)


async def health_tool() -> str:
    async with tool_session() as db:
        return await health(db, CLOCK)


default_registry.register(
    ToolSpec(
        "brief",
        "Summarise today for the owner: finished work, decisions waiting, today's spend. "
        "Read-only. The answer is already phrased for speech; read it aloud as it is.",
        READ_ONLY,
        brief_tool,
    )
)
default_registry.register(
    ToolSpec(
        "inbox",
        "List what waits for the owner: approvals (references like A12) and agent questions "
        "(references like Q7). Read-only. Read the answer aloud as it is, then wait for a "
        "decision or an answer.",
        READ_ONLY,
        inbox_tool,
    )
)
default_registry.register(
    ToolSpec(
        "health",
        "Report whether the machines that run the agents are up. Read-only. Read the answer "
        "aloud as it is.",
        READ_ONLY,
        health_tool,
    )
)
