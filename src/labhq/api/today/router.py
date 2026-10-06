"""`GET /api/today`."""

from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Query

from labhq.api.deps import ClockDep, SessionDep
from labhq.api.today import queries
from labhq.api.today.schemas import CeoReport, Today
from labhq.ceoreports import latest_report
from labhq.clock import ensure_utc

DEFAULT_WINDOW = timedelta(hours=24)

router = APIRouter(prefix="/today", tags=["today"])


@router.get("")
async def today_get(
    db: SessionDep,
    clock: ClockDep,
    since: Annotated[
        datetime | None, Query(description="Start of the window; default: the last 24 hours.")
    ] = None,
) -> Today:
    """What was delivered since `since`, and what needs the owner now."""
    now = clock.now()
    start = ensure_utc(since) if since else now - DEFAULT_WINDOW
    delivered = await queries.deliverables(db, start)
    report = await latest_report(db)
    return Today(
        since=start,
        until=now,
        ceo_report=CeoReport.model_validate(report, from_attributes=True) if report else None,
        deliverables=delivered,
        needs_you=await queries.needs_you(db, clock),
        spend_without_output=await queries.spend_without_output(db, start, delivered),
    )
