"""`labhq mcp internal --call <id>`: the Call Center's tools over stdio (ADR 0004).

The Call Center agent's CLI, in tmux, starts this as its child process. Nothing listens on
a port, so nothing reaches the tunnel. It serves the same `CallTools` the SDK adapter
serves in process, bound to one call, with the same bounds: `deliver` and `interrupt` take
a request id of that call, never free text, and an interrupt needs the owner's own words.

This process holds no running agents, so an interrupt the owner asked for still queues the
owner's words for the end of the agent's turn, as `labhq mcp serve` alone does.
"""

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.adapters import AgentTool
from labhq.agenttools.stdio import serve_stdio
from labhq.callcenter.calls import CallTools, Interrupter, NoInterrupter
from labhq.callcenter.screens import ScreenReader
from labhq.clock import Clock
from labhq.db.models import Call


async def internal_tools(
    sessions: async_sessionmaker[AsyncSession],
    clock: Clock,
    call_id: int,
    *,
    screens: ScreenReader | None,
    interrupter: Interrupter | None = None,
) -> list[AgentTool]:
    """The tools of `call_id`; the caller never names another call."""
    async with sessions() as db:
        if await db.get(Call, call_id) is None:
            raise LookupError(f"there is no call {call_id}")
    tools = CallTools(sessions, clock, interrupter or NoInterrupter(), call_id, screens)
    return tools.specs()


async def serve_internal(tools: Sequence[AgentTool]) -> None:
    await serve_stdio(tools)
