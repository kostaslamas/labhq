import re
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from labhq.callcenter.answers import brief, health, inbox, parse_ref
from labhq.clock import FakeClock
from labhq.db.enums import RiskClass
from labhq.db.models import Approval
from labhq.speech import speakable
from tests.callcenter.answers.seed import seed_busy


async def test_every_answer_is_speakable_on_an_empty_database(
    session: AsyncSession, clock: FakeClock
) -> None:
    for text in (await brief(session, clock), await inbox(session), await health(session, clock)):
        assert text
        assert speakable(text) == text


async def test_every_answer_is_speakable_on_a_busy_database(
    session: AsyncSession, clock: FakeClock
) -> None:
    await seed_busy(session, clock)
    for text in (await brief(session, clock), await inbox(session), await health(session, clock)):
        assert speakable(text) == text


async def test_brief_names_deliverables_and_pending_decisions(
    session: AsyncSession, clock: FakeClock
) -> None:
    await seed_busy(session, clock)
    text = await brief(session, clock)
    assert "Ship the login page" in text
    assert "One task finished" in text
    assert "One approval went through" in text
    assert "one approval and one question" in text
    assert "Today's spend is 1 dollar and 23 cents" in text


async def test_brief_never_reports_activity(session: AsyncSession, clock: FakeClock) -> None:
    await seed_busy(session, clock)
    text = (await brief(session, clock)).lower()
    assert "working" not in text
    assert "running" not in text


async def test_brief_on_an_empty_database_says_so(session: AsyncSession, clock: FakeClock) -> None:
    text = await brief(session, clock)
    assert "Nothing was delivered today" in text
    assert "Nothing is waiting on you" in text


async def test_brief_respects_since(session: AsyncSession, clock: FakeClock) -> None:
    await seed_busy(session, clock)
    recent = await brief(session, clock, since=clock.now() - timedelta(minutes=15))
    assert "Nothing was delivered since 15 minutes ago" in recent
    older = await brief(session, clock, since=clock.now() - timedelta(hours=3))
    assert "One task finished since 3 hours ago" in older


async def test_inbox_lists_references_the_owner_can_say_back(
    session: AsyncSession, clock: FakeClock
) -> None:
    ids = await seed_busy(session, clock)
    text = await inbox(session)
    refs = re.findall(r"\b[AQ]\d+\b", text)
    assert sorted(parse_ref(ref) for ref in refs) == [
        ("approval", ids["approval"]),
        ("question", ids["question"]),
    ]
    assert "heavy merge branch" in text
    assert "Which branch should I release from?" in text


async def test_inbox_empty(session: AsyncSession) -> None:
    assert await inbox(session) == "Your inbox is empty."


async def test_inbox_long_lists_stay_short(session: AsyncSession, clock: FakeClock) -> None:
    session.add_all(
        Approval(type="push", risk_class=RiskClass.LIGHT, created_at=clock.now()) for _ in range(30)
    )
    await session.commit()
    text = await inbox(session)
    assert "27 more approvals are waiting" in text
    assert text.count("Approval A") == 3


async def test_health_reports_incidents_and_latest_samples(
    session: AsyncSession, clock: FakeClock
) -> None:
    await seed_busy(session, clock)
    text = await health(session, clock)
    assert "build-box is degraded" in text
    assert "One incident open" in text
    assert "Disk almost full on build-box, opened 3 hours ago" in text
    assert "disk use on / is 93 percent" in text
    assert "80 percent" not in text


async def test_health_with_no_hosts(session: AsyncSession, clock: FakeClock) -> None:
    assert await health(session, clock) == (
        "No machines are registered yet. No agent runs active out of 8 allowed, "
        "and 75 percent of memory is free."
    )
