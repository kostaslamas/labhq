"""What a meeting cost: the cost events of the runs behind its transcript entries.

Every run a meeting starts, turn or minutes, leaves a transcript entry with its run id, so
the entries are the meeting's ledger. The cost events carry the project, so the project
budget counts them with no meeting-specific code (plan §7).
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.budgets.decision import require_micros
from labhq.db.models import CostEvent, MeetingTranscriptEntry


async def meeting_cost_micros(db: AsyncSession, meeting_id: int) -> int:
    runs = (
        select(MeetingTranscriptEntry.run_id)
        .where(
            MeetingTranscriptEntry.meeting_id == meeting_id,
            MeetingTranscriptEntry.run_id.is_not(None),
        )
        .distinct()
    )
    total = await db.scalar(
        select(func.coalesce(func.sum(CostEvent.cost_micros), 0)).where(CostEvent.run_id.in_(runs))
    )
    return require_micros("meeting_cost_micros", total)
