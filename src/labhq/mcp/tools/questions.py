"""Answer an agent's question with the owner's words.

`answer` in the core needs a call and a stored request: the words are stored as a
`call_requests` row in the current call first, as `ask_ceo` stores its questions.
"""

from mcp.types import ToolAnnotations

from labhq.callcenter.answers.refs import parse_ref
from labhq.callcenter.calls import record_request
from labhq.callcenter.questions import answer
from labhq.db.enums import CallRequestStatus
from labhq.mcp.tools.registry import ToolSpec, default_registry
from labhq.mcp.tools.runtime import CLOCK, tool_session
from labhq.speech import speakable

# Answers go to an agent as one short instruction, not a transcript.
MAX_WORDS = 60


def _names_a_question(reference: str) -> bool:
    try:
        kind, _ = parse_ref(reference)
    except ValueError:
        return False
    return kind == "question"


async def answer_tool(reference: str, words: str) -> str:
    if not _names_a_question(reference):
        return speakable("Say which question you are answering, like Q 7.")
    words = " ".join(words.split())
    if not words:
        return speakable("I did not hear the answer.")
    if len(words.split()) > MAX_WORDS:
        return speakable(f"Keep the answer under {MAX_WORDS} words and try again.")
    async with tool_session() as db:
        try:
            request = await record_request(db, CLOCK, words)
            # The program handles this request itself; the Call Center agent must not pick it up.
            request.status = CallRequestStatus.ANSWERED
            request.answered_at = request.created_at
            return await answer(
                db, CLOCK, reference, call_id=request.call_id, request_id=request.request_id
            )
        except Exception:
            # Nothing is committed on a failure, so no orphan request is left behind.
            await db.rollback()
            raise


default_registry.register(
    ToolSpec(
        "answer",
        "Answer an agent's question with the owner's own words. reference is the spoken "
        "handle of the question, like Q7. words is what the owner said, passed on as spoken "
        "and never rewritten or extended. Keep it short: a sentence or two, at most "
        f"{MAX_WORDS} words. The answer reaches the agent when its current turn ends.",
        ToolAnnotations(readOnlyHint=False, destructiveHint=False),
        answer_tool,
    )
)
