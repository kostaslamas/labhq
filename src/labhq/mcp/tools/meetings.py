"""`meeting_minutes`: what a meeting decided, read from the database with no agent."""

from mcp.types import ToolAnnotations

from labhq.callcenter.answers.minutes import meeting_minutes
from labhq.mcp.tools.registry import ToolSpec, default_registry
from labhq.mcp.tools.runtime import CLOCK, tool_session


async def meeting_minutes_tool(meeting: str | None = None) -> str:
    async with tool_session() as db:
        return await meeting_minutes(db, CLOCK, meeting)


default_registry.register(
    ToolSpec(
        "meeting_minutes",
        "Read the minutes of a meeting: who took part, the decisions, the action items with "
        "their owners and task status, and the cost. Read-only. meeting is what the owner "
        "said about which one, like this morning's standup, the last planning of a project "
        "or M4; leave it out for the latest meeting. If the answer asks which one, ask the "
        "owner and call again with their words or the meeting number. Read the answer aloud "
        "as it is.",
        ToolAnnotations(readOnlyHint=True),
        meeting_minutes_tool,
    )
)
