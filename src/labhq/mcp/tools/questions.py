"""Answer an agent's question with the owner's words.

`answer` in the core needs a call and a stored request. The ask-the-owner flow (#39) will
create both; until it lands this tool opens or reuses a call inside the call window and
stores the words as a `call_requests` row itself. #39 should replace `_record_request` with
its own request handling and keep the rest.
"""

import uuid
from datetime import timedelta

from mcp.types import ToolAnnotations
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.callcenter.answers.refs import parse_ref
from labhq.callcenter.questions import answer
from labhq.callcenter.settings import get_callcenter_settings
from labhq.clock import Clock
from labhq.db.enums import CallStatus
from labhq.db.models import Call, CallRequest
from labhq.mcp.tools.registry import ToolSpec, default_registry
from labhq.mcp.tools.runtime import CLOCK, tool_session
from labhq.speech import speakable

# Answers go to an agent as one short instruction, not a transcript.
MAX_WORDS = 60


async def _current_call(db: AsyncSession, clock: Clock) -> Call:
    now = clock.now()
    window_start = now - timedelta(seconds=get_callcenter_settings().call_window_seconds)
    call = await db.scalar(
        select(Call)
        .where(Call.status == CallStatus.OPEN, Call.last_activity_at >= window_start)
        .order_by(Call.last_activity_at.desc())
    )
    if call is None:
        call = Call(opened_at=now, last_activity_at=now)
        db.add(call)
    else:
        call.last_activity_at = now
    await db.flush()
    return call


async def _record_request(db: AsyncSession, clock: Clock, words: str) -> tuple[int, str]:
    call = await _current_call(db, clock)
    request_id = f"mcp-{uuid.uuid4().hex}"
    db.add(CallRequest(call_id=call.id, request_id=request_id, text=words, created_at=clock.now()))
    await db.flush()
    return call.id, request_id


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
            call_id, request_id = await _record_request(db, CLOCK, words)
            return await answer(db, CLOCK, reference, call_id=call_id, request_id=request_id)
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
