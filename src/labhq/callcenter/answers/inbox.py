"""`inbox`: pending approvals and open agent questions, each with a reference to say back."""

from sqlalchemy.ext.asyncio import AsyncSession

from labhq.callcenter.answers.pending import count_pending, open_questions, pending_approvals
from labhq.callcenter.answers.phrasing import FREE_TEXT_WORDS, LISTED, clean
from labhq.callcenter.answers.refs import approval_ref, question_ref
from labhq.db.enums import RiskClass
from labhq.speech import join_sentences, say_count, speakable


async def inbox(db: AsyncSession) -> str:
    approvals_total, questions_total = await count_pending(db)
    if approvals_total + questions_total == 0:
        return speakable("Your inbox is empty.")

    parts = [
        f"You have {say_count(approvals_total, 'approval')} "
        f"and {say_count(questions_total, 'question')} waiting"
    ]
    for approval, task_title in await pending_approvals(db, LISTED):
        weight = "heavy " if approval.risk_class is RiskClass.HEAVY else ""
        subject = f" for {clean(task_title)}" if task_title else ""
        action = clean(approval.type)
        parts.append(f"Approval {approval_ref(approval.id)}: {weight}{action}{subject}")
    if approvals_total > LISTED:
        parts.append(f"{approvals_total - LISTED} more approvals are waiting")

    for question, agent_title in await open_questions(db, LISTED):
        asked = clean(question.question, FREE_TEXT_WORDS)
        parts.append(f"Question {question_ref(question.id)} from {clean(agent_title)}: {asked}")
    if questions_total > LISTED:
        parts.append(f"{questions_total - LISTED} more questions are waiting")
    return speakable(join_sentences(parts))
