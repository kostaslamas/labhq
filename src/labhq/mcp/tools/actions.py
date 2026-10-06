"""Write tools that change state: decide an approval, send an order to the CEO, ask to merge."""

import uuid

from mcp.types import ToolAnnotations

from labhq.callcenter.actions import decide, order
from labhq.mcp.tools.registry import ToolSpec, default_registry
from labhq.mcp.tools.runtime import CLOCK, tool_session


async def decide_tool(reference: str, verdict: str) -> str:
    async with tool_session() as db:
        return await decide(db, CLOCK, reference, verdict)


async def order_tool(
    text: str = "",
    request_id: str | None = None,
    project: str | None = None,
    merge: int | None = None,
) -> str:
    # A retry that repeats the request id sends nothing twice; without one, every call is new.
    key = request_id or f"mcp-{uuid.uuid4().hex[:24]}"
    async with tool_session() as db:
        return await order(db, CLOCK, text=text, request_id=key, project=project, merge=merge)


default_registry.register(
    ToolSpec(
        "decide",
        "Approve or reject one pending approval. reference is the spoken handle, like A12. "
        "verdict is approve or reject. Heavy approvals (push, merge, deleting, budget "
        "overruns) can never be approved by voice: the call leaves them pending and tells "
        "the owner to confirm with the passkey. Say what you are deciding and get the "
        "owner's clear yes before calling.",
        ToolAnnotations(readOnlyHint=False, destructiveHint=True),
        decide_tool,
    )
)
default_registry.register(
    ToolSpec(
        "order",
        "Send the owner's order or request to the CEO, who passes it down to managers and "
        "workers. text is exactly what the owner said, never reworded, shortened or "
        "extended; nothing else is sent with it. request_id is an optional key that makes a "
        "retry send nothing twice. To merge a finished task into main instead, set project "
        "and merge to its task id and leave text empty: that only requests the merge, which "
        "the owner approves with the passkey.",
        ToolAnnotations(readOnlyHint=False, destructiveHint=False),
        order_tool,
    )
)
