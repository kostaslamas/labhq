"""What waits on the owner: pending approvals and open agent questions."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.db.enums import ApprovalStatus, QuestionStatus
from labhq.db.models import Agent, AgentQuestion, Approval, Task


async def count_pending(db: AsyncSession) -> tuple[int, int]:
    approvals = await db.scalar(
        select(func.count()).select_from(Approval).where(Approval.status == ApprovalStatus.PENDING)
    )
    questions = await db.scalar(
        select(func.count())
        .select_from(AgentQuestion)
        .where(AgentQuestion.status == QuestionStatus.PENDING)
    )
    return approvals or 0, questions or 0


async def pending_approvals(db: AsyncSession, limit: int) -> list[tuple[Approval, str | None]]:
    rows = await db.execute(
        select(Approval, Task.title)
        .outerjoin(Task, Task.id == Approval.task_id)
        .where(Approval.status == ApprovalStatus.PENDING)
        .order_by(Approval.created_at, Approval.id)
        .limit(limit)
    )
    return [(approval, title) for approval, title in rows.all()]


async def open_questions(db: AsyncSession, limit: int) -> list[tuple[AgentQuestion, str]]:
    rows = await db.execute(
        select(AgentQuestion, Agent.title)
        .join(Agent, Agent.id == AgentQuestion.agent_id)
        .where(AgentQuestion.status == QuestionStatus.PENDING)
        .order_by(AgentQuestion.created_at, AgentQuestion.id)
        .limit(limit)
    )
    return [(question, title) for question, title in rows.all()]
