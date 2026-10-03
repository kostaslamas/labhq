"""Write tools that change state: decide an approval, order a task."""

import uuid

from mcp.types import ToolAnnotations

from labhq.callcenter.actions import decide, order
from labhq.mcp.tools.registry import ToolSpec, default_registry
from labhq.mcp.tools.runtime import CLOCK, tool_session


async def decide_tool(reference: str, verdict: str) -> str:
    async with tool_session() as db:
        return await decide(db, CLOCK, reference, verdict)


async def order_tool(
    project: str, text: str, assignee: int | None = None, request_id: str | None = None
) -> str:
    # A retry that repeats the request id creates nothing; without one, every call is new.
    key = request_id or f"mcp-{uuid.uuid4().hex}"
    async with tool_session() as db:
        return await order(db, CLOCK, project=project, text=text, request_id=key, assignee=assignee)


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
        "Create a task in a project and wake its assignee. project is the project name, "
        "text is the owner's instruction in a sentence or two, assignee is an optional "
        "agent id, request_id is an optional key that makes a retry create nothing twice. "
        "The answer names the task with a reference like T3.",
        ToolAnnotations(readOnlyHint=False, destructiveHint=False),
        order_tool,
    )
)
