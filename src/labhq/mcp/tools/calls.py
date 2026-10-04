"""`ask_ceo` and `get_reply`: the async pair. A ticket, or the answer if it comes in time.

The Call Center lives as long as the server process, so its workers keep running between
tool calls. One instance per database, built on first use.
"""

from functools import cache

from mcp.types import ToolAnnotations

from labhq.callcenter.calls import CallCenter, Interrupter, NoInterrupter, Reply, TicketState
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
    TicketState.EXPIRED: "That ticket has expired. Ask the question again.",
    TicketState.UNKNOWN: "I have no ticket by that name. Ask the question again.",
}
SPOKEN_WORKING = (
    "Still working on it. Call get reply again with ticket {ticket}. Do not ask the question again."
)
DEFAULT_WAIT_SECONDS = 25


# `labhq serve` holds the scheduler in this process and attaches it, so interrupt reaches
# live runs; `labhq mcp serve` alone holds none.
_interrupter: Interrupter = NoInterrupter()


def attach_interrupter(interrupter: Interrupter) -> None:
    """Call before the first tool call: the Call Center is built once per database."""
    global _interrupter
    _interrupter = interrupter


@cache
def _call_center(database_url: str) -> CallCenter:
    settings = Settings()
    sessions = session_factory(create_engine(database_url))
    return CallCenter(
        sessions,
        CLOCK,
        workdir=settings.data_dir / CALL_CENTER_DIR,
        agent_settings=CallAgentSettings(),
        interrupter=_interrupter,
    )


def call_center() -> CallCenter:
    return _call_center(Settings().resolved_database_url)


def _answer(reply: Reply, ticket: str) -> str:
    if reply.text is not None:
        return speakable(reply.text)
    if reply.state is TicketState.WORKING:
        return speakable(SPOKEN_WORKING.format(ticket=ticket))
    return speakable(SPOKEN[reply.state])


async def ask_ceo_tool(question: str, wait_seconds: int = 0) -> str:
    question = " ".join(question.split())
    if not question:
        return speakable("I did not hear the question.")
    if len(question.split()) > MAX_WORDS:
        return speakable(f"Keep the question under {MAX_WORDS} words and try again.")
    center = call_center()
    ticket = await center.ask(question)
    if wait_seconds > 0:
        return _answer(await center.wait_for_reply(ticket.ticket, wait_seconds), ticket.ticket)
    return speakable(
        f"Your ticket is {ticket.ticket}. The Call Center is looking into it. "
        "Call get reply with that ticket in a few seconds."
    )


async def get_reply_tool(ticket: str, wait_seconds: int = DEFAULT_WAIT_SECONDS) -> str:
    ticket = ticket.strip()
    reply = await call_center().wait_for_reply(ticket, wait_seconds)
    return _answer(reply, ticket)


default_registry.register(
    ToolSpec(
        "ask_ceo",
        "Ask the Call Center something that needs reading and judgement: what an agent is "
        "doing, why something is stuck, or to pass the owner's words to an agent. question "
        "is what the owner said, as spoken. wait_seconds (0 to 50, default 0) makes the call wait "
        "for the answer and return it directly; when it returns a ticket or says it is still "
        "working, call get_reply with that ticket and never ask the question again. "
        "Questions a few minutes apart share one call and keep its context.",
        ToolAnnotations(readOnlyHint=False, destructiveHint=False),
        ask_ceo_tool,
    )
)
default_registry.register(
    ToolSpec(
        "get_reply",
        "Collect the Call Center's answer for a ticket from ask_ceo. Read-only. It waits up to "
        "wait_seconds (default 25, at most 50) and returns as soon as the answer is ready. If "
        "it says working, call get_reply again with the same ticket, never ask again. Read "
        "the answer aloud as it is.",
        ToolAnnotations(readOnlyHint=True),
        get_reply_tool,
    )
)
