"""Which model the agents use, read back from the policy table, and a request to change it."""

from mcp.types import ToolAnnotations

from labhq.callcenter.answers.models import models_answer, request_model_change
from labhq.mcp.tools.registry import ToolSpec, default_registry
from labhq.mcp.tools.runtime import CLOCK, tool_session


async def models_tool() -> str:
    async with tool_session() as db:
        return await models_answer(db)


async def change_models_tool(key: str, model: str, effort: str) -> str:
    async with tool_session() as db:
        return await request_model_change(db, CLOCK, key=key, model=model, effort=effort)


default_registry.register(
    ToolSpec(
        "models",
        "Say which model and effort each role (worker, manager, CEO) and task kind (summary, "
        "check) uses. Read-only. Read the answer aloud as it is.",
        ToolAnnotations(readOnlyHint=True),
        models_tool,
    )
)
default_registry.register(
    ToolSpec(
        "change_models",
        "Ask to change the model of one role or task kind. key is the role or task kind "
        "(worker, manager, ceo, summary, check, ...), model is a model ID the owner named, "
        "effort is low, medium, high, xhigh or max. This only requests the change: the owner "
        "confirms it with the passkey, never by voice. Get the owner's clear yes first.",
        ToolAnnotations(readOnlyHint=False, destructiveHint=False),
        change_models_tool,
    )
)
