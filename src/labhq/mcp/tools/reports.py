"""Read-only tools: what happened, what agents reported, what waits, how the machines are."""

from mcp.types import ToolAnnotations

from labhq.callcenter.answers import brief, health, inbox, reports
from labhq.mcp.tools.registry import ToolSpec, default_registry
from labhq.mcp.tools.runtime import CLOCK, tool_session

READ_ONLY = ToolAnnotations(readOnlyHint=True)


async def brief_tool() -> str:
    async with tool_session() as db:
        return await brief(db, CLOCK)


async def inbox_tool() -> str:
    async with tool_session() as db:
        return await inbox(db)


async def reports_tool(project: str | None = None) -> str:
    async with tool_session() as db:
        return await reports(db, CLOCK, project)


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
default_registry.register(
    ToolSpec(
        "reports",
        "Answer what an agent is doing or how far a project is from what workers and their "
        "supervisors last reported: who reported, how long ago, what they said, the task "
        "status and their last run. Read-only; it wakes nobody. project is the project's "
        "name, or leave it out for every project. Read the answer aloud as it is.",
        READ_ONLY,
        reports_tool,
    )
)
