"""What bounds the Call Center's write tools: only the owner's stored words go anywhere.

ADR 0004: pane text, logs and status files can carry instructions. So a write tool takes
the id of a request of this call, never free text, and the stored words are what is sent.
Every refusal is a `BoundError` whose message the agent reads.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.db.models import CallRequest


class BoundError(PermissionError):
    """The Call Center asked for something the owner did not."""


async def stored_request(db: AsyncSession, call_id: int, request_id: str) -> CallRequest:
    request = await db.scalar(
        select(CallRequest).where(
            CallRequest.request_id == request_id, CallRequest.call_id == call_id
        )
    )
    if request is None:
        raise BoundError(f"Request {request_id} is not part of this call.")
    return request
