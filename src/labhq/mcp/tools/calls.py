"""`ask_ceo` and `get_reply`: the async pair. A ticket at once, the answer when it is ready.

The Call Center lives as long as the server process, so its workers keep running between
tool calls. One instance per database, built on first use.
"""

from functools import cache

from mcp.types import ToolAnnotations

from labhq.callcenter.calls import CallCenter, TicketState
from labhq.callcenter.calls.settings import CallAgentSettings
from labhq.db import create_engine, session_factory
from labhq.mcp.tools.registry import ToolSpec, default_registry
from labhq.mcp.tools.runtime import CLOCK
from labhq.settings import Settings
from labhq.speech import speakable

CALL_CENTER_DIR = "callcenter"
# A question is a sentence or a few; a long dictation belongs in an order.
MAX_WORDS = 120

SPOKEN: dict[TicketState, str] = {
    TicketState.WORKING: "Still working on it. Ask again with the same ticket in a few seconds.",
    TicketState.EXPIRED: "That ticket has expired. Ask the question again.",
    TicketState.UNKNOWN: "I have no ticket by that name. Ask the question again.",
}


@cache
def _call_center(database_url: str) -> CallCenter:
    settings = Settings()
    sessions = session_factory(create_engine(database_url))
    return CallCenter(
        sessions,
        CLOCK,
        workdir=settings.data_dir / CALL_CENTER_DIR,
        agent_settings=CallAgentSettings(),
    )


def call_center() -> CallCenter:
    return _call_center(Settings().resolved_database_url)


async def ask_ceo_tool(question: str) -> str:
    question = " ".join(question.split())
    if not question:
        return speakable("I did not hear the question.")
    if len(question.split()) > MAX_WORDS:
        return speakable(f"Keep the question under {MAX_WORDS} words and try again.")
    ticket = await call_center().ask(question)
    return speakable(
        f"Your ticket is {ticket.ticket}. The Call Center is looking into it. "
        "Call get reply with that ticket in a few seconds."
    )


async def get_reply_tool(ticket: str) -> str:
    reply = await call_center().reply(ticket.strip())
    if reply.text is not None:
        return speakable(reply.text)
    return speakable(SPOKEN[reply.state])


default_registry.register(
    ToolSpec(
        "ask_ceo",
        "Ask the Call Center something that needs reading and judgement: what an agent is "
        "doing, why something is stuck, or to pass the owner's words to an agent. question "
        "is what the owner said, as spoken. Returns a ticket at once; then call get_reply "
        "with it. Questions a few minutes apart share one call and keep its context.",
        ToolAnnotations(readOnlyHint=False, destructiveHint=False),
        ask_ceo_tool,
    )
)
default_registry.register(
    ToolSpec(
        "get_reply",
        "Collect the Call Center's answer for a ticket from ask_ceo. Read-only. If it says "
        "it is still working, wait a few seconds and ask again with the same ticket. Read "
        "the answer aloud as it is.",
        ToolAnnotations(readOnlyHint=True),
        get_reply_tool,
    )
)
