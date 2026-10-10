"""`meeting_cost`: what the decision room costs or will cost, read from the database with no agent."""

from mcp.types import ToolAnnotations

from labhq.callcenter.answers.room_cost import room_cost
from labhq.mcp.tools.registry import ToolSpec, default_registry
from labhq.mcp.tools.runtime import CLOCK, tool_session


async def meeting_cost_tool() -> str:
    async with tool_session() as db:
        return await room_cost(db, CLOCK)


default_registry.register(
    ToolSpec(
        "meeting_cost",
        "How much the latest decision room will cost or has cost: the expected range, the "
        "hard cap, what it has cost so far over how many turns, and the share of the plan "
        "window used when it runs on a subscription. Use it for how much did it cost or how "
        "much will it cost. Read-only. Read the answer aloud as it is, and say equivalent "
        "cost where the answer says so: a subscription has no bill.",
        ToolAnnotations(readOnlyHint=True),
        meeting_cost_tool,
    )
)
