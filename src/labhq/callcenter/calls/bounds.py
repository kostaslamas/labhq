"""The two tools that reach working agents, bounded so only the owner speaks through them.

ADR 0004: pane text, logs and status files can carry instructions, and working agents run
with `bypassPermissions`. So a delivery carries the stored words of a request of this call,
chosen by its id; the recipient is an agent the owner named in that request or one with a
pending question; an interrupt needs the owner's own words asking for it, at most once per
request. Every refusal is a `BoundError` whose message the agent reads.
"""

import re
from typing import TYPE_CHECKING, Protocol

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.callcenter.deliveries import deliver
from labhq.clock import Clock
from labhq.db.enums import QuestionStatus
from labhq.db.models import Agent, AgentQuestion, CallRequest, Delivery

if TYPE_CHECKING:
    from labhq.scheduler import Scheduler

MESSAGE_LABEL = "Message from the owner"
# The owner's explicit ask, in the stored words; nothing else can trigger an interrupt.
INTERRUPT_REQUEST = re.compile(r"\binterrupt", re.IGNORECASE)


class BoundError(PermissionError):
    """The Call Center asked for something the owner did not."""


class Interrupter(Protocol):
    """Stops an agent's current turn; returns whether a running turn was stopped."""

    async def interrupt(self, agent_id: int) -> bool: ...


class NoInterrupter:
    """For a process that holds no running agents, such as `labhq mcp serve` alone.

    Reaching runs another process holds waits for the tmux adapter (ADR 0003). The message
    is still delivered when the agent's turn ends.
    """

    async def interrupt(self, agent_id: int) -> bool:
        return False


class SchedulerInterrupter:
    """Interrupts runs held by a scheduler in this process, as `labhq serve` runs one."""

    def __init__(self, scheduler: "Scheduler") -> None:
        self._scheduler = scheduler

    async def interrupt(self, agent_id: int) -> bool:
        return await self._scheduler.interrupt_agent(agent_id)


def names(text: str, agent: Agent) -> bool:
    """Whether the owner named `agent` in `text`: by its title, or as agent and its id."""
    title = re.escape(" ".join(agent.title.split()))
    by_title = re.search(rf"(?<!\w){title}(?!\w)", text, re.IGNORECASE)
    by_id = re.search(rf"\bagent\s*#?\s*{agent.id}\b", text, re.IGNORECASE)
    return bool(by_title or by_id)


async def stored_request(db: AsyncSession, call_id: int, request_id: str) -> CallRequest:
    request = await db.scalar(
        select(CallRequest).where(
            CallRequest.request_id == request_id, CallRequest.call_id == call_id
        )
    )
    if request is None:
        raise BoundError(f"Request {request_id} is not part of this call.")
    return request


async def has_pending_question(db: AsyncSession, agent_id: int) -> bool:
    return bool(
        await db.scalar(
            select(
                exists().where(
                    AgentQuestion.agent_id == agent_id,
                    AgentQuestion.status == QuestionStatus.PENDING,
                )
            )
        )
    )


async def recipient(db: AsyncSession, request: CallRequest, agent_id: int) -> Agent:
    agent = await db.get(Agent, agent_id)
    if agent is None:
        raise BoundError(f"There is no agent {agent_id}.")
    if not names(request.text, agent) and not await has_pending_question(db, agent_id):
        raise BoundError(
            f"The owner did not name {agent.title} in request {request.request_id}, "
            "and it has no pending question."
        )
    return agent


async def _already_delivered(
    db: AsyncSession, request_id: str, agent_id: int, *, interrupted: bool | None = None
) -> bool:
    query = exists().where(Delivery.request_id == request_id)
    if interrupted is None:
        query = query.where(Delivery.recipient_agent_id == agent_id)
    else:
        query = query.where(Delivery.interrupted.is_(interrupted))
    return bool(await db.scalar(select(query)))


async def deliver_request(
    db: AsyncSession, clock: Clock, *, call_id: int, request_id: str, agent_id: int
) -> str:
    """Queue the words of `request_id` for `agent_id`. Commits."""
    request = await stored_request(db, call_id, request_id)
    agent = await recipient(db, request, agent_id)
    if await _already_delivered(db, request_id, agent_id):
        return f"Request {request_id} was already delivered to {agent.title}."
    result = await deliver(
        db,
        clock,
        call_id=call_id,
        request_id=request_id,
        agent_id=agent_id,
        task_id=None,
        text=request.text,
        label=MESSAGE_LABEL,
    )
    await db.commit()
    if result.delivery is None:
        return f"{agent.title} cannot wake now, it is over budget. Nothing was delivered."
    return f"Delivered to {agent.title}; it reads the owner's words when its turn ends."


async def interrupt_request(
    db: AsyncSession,
    clock: Clock,
    interrupter: Interrupter,
    *,
    call_id: int,
    request_id: str,
    agent_id: int,
) -> str:
    """Interrupt `agent_id` and deliver the words of `request_id`, if the owner asked. Commits."""
    request = await stored_request(db, call_id, request_id)
    if not INTERRUPT_REQUEST.search(request.text):
        raise BoundError(f"The owner did not ask for an interrupt in request {request_id}.")
    agent = await recipient(db, request, agent_id)
    if await _already_delivered(db, request_id, agent_id, interrupted=True):
        raise BoundError(f"Request {request_id} already interrupted an agent.")
    result = await deliver(
        db,
        clock,
        call_id=call_id,
        request_id=request_id,
        agent_id=agent_id,
        task_id=None,
        text=request.text,
        label=MESSAGE_LABEL,
    )
    if result.delivery is None:
        await db.commit()
        return f"{agent.title} cannot wake now, it is over budget. Nothing was delivered."
    # The words are queued before the turn stops, so the next turn starts with them.
    result.delivery.interrupted = await interrupter.interrupt(agent_id)
    await db.commit()
    if result.delivery.interrupted:
        return f"Interrupted {agent.title}; it continues with the owner's words."
    return (
        f"Could not interrupt {agent.title} from here; "
        "it reads the owner's words when its turn ends."
    )
