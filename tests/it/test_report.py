"""The daily report: one timer wake-up per local day, at the configured time."""

from datetime import time

import pytest
from pydantic import ValidationError

from labhq.db.enums import WakeupSource
from labhq.db.models import Agent
from labhq.it import REPORT_REASON, ItSettings, report_key
from labhq.scheduler import Outcome
from tests.it.conftest import DepartmentFactory
from tests.roles.conftest import Org

# The org's clock starts at 09:00 UTC.


async def test_no_report_before_its_time(org: Org, department: DepartmentFactory) -> None:
    result = await (await department(report_time=time(9, 30))).tick()
    assert result.report is None
    assert await org.wakeups() == []


async def test_one_report_a_day_once_its_time_has_come(
    org: Org, department: DepartmentFactory
) -> None:
    it = await department(report_time=time(9, 30))
    org.clock.advance(1800)

    first = await it.tick()
    org.clock.advance(3600)
    again = await it.tick()
    org.clock.advance(24 * 3600)
    tomorrow = await it.tick()

    assert first.report is not None and again.report is not None and tomorrow.report is not None
    assert [first.report.outcome, again.report.outcome, tomorrow.report.outcome] == [
        Outcome.CREATED,
        Outcome.DUPLICATE,
        # Yesterday's report never ran, so today's merges into it instead of piling up.
        Outcome.COALESCED,
    ]
    pending, merged = await org.wakeups()
    assert (pending.source, pending.task_id, pending.reason) == (
        WakeupSource.TIMER,
        None,
        REPORT_REASON,
    )
    assert pending.coalesced_count == 1
    assert merged.idempotency_key.endswith(":2026-10-03")


async def test_the_report_time_is_local_to_its_time_zone(
    org: Org, department: DepartmentFactory
) -> None:
    # 09:00 UTC is 12:00 in Athens in October: the 11:00 report is due, the UTC one is not.
    it = await department(report_time=time(11, 0), report_timezone="Europe/Athens")
    athens = await it.tick()
    assert athens.report is not None and athens.agent_id is not None
    assert athens.report.request.idempotency_key.endswith(":2026-10-02")


def test_the_report_key_names_the_agent_and_the_day() -> None:
    assert report_key(Agent(id=7), "2026-10-02") == "it:report:agent:7:2026-10-02"


def test_an_unknown_time_zone_is_refused() -> None:
    with pytest.raises(ValidationError, match="unknown time zone"):
        ItSettings(report_timezone="Mars/Olympus")
