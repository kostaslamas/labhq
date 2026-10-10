"""A change to the table is asked for, approved with a passkey, then applied by the engine."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.approvals import ApprovalService
from labhq.approvals.service import ConfirmationNotAllowedError
from labhq.callcenter.answers.models import models_answer, request_model_change
from labhq.clock import FakeClock
from labhq.db.enums import ApprovalStatus
from labhq.modelpolicy import load_policy
from labhq.speech import speakable


@pytest.fixture(autouse=True)
def engine_database(database_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LABHQ_DATABASE_URL", database_url)


async def test_the_call_center_reads_the_table_back(session: AsyncSession) -> None:
    answer = await models_answer(session)
    assert speakable(answer) == answer
    assert "Haiku 5.5 at medium effort for summary, check" in answer
    assert "Sonnet 5.5 at medium effort for worker" in answer


async def test_a_voice_request_only_creates_a_heavy_approval_and_changes_nothing(
    session: AsyncSession, clock: FakeClock
) -> None:
    sentence = await request_model_change(
        session, clock, key="worker", model="claude-opus-5-5", effort="high"
    )
    assert "passkey" in sentence
    assert (await load_policy(session)).rows["worker"].model == "claude-sonnet-5-5"

    service = ApprovalService(async_sessionmaker(session.bind, expire_on_commit=False), clock=clock)  # type: ignore[arg-type]
    (pending,) = await service.list(ApprovalStatus.PENDING)
    assert pending.type == "change_models"
    with pytest.raises(ConfirmationNotAllowedError):
        await service.approve(pending.id, decider="owner", confirmation="voice")
    assert (await load_policy(session)).rows["worker"].model == "claude-sonnet-5-5"

    await service.approve(pending.id, decider="owner", confirmation="passkey")
    # The executor committed on its own connection; end this session's read snapshot first.
    await session.rollback()
    assert (await load_policy(session)).rows["worker"].model == "claude-opus-5-5"


async def test_an_unknown_model_is_refused_before_any_approval(
    session: AsyncSession, clock: FakeClock
) -> None:
    sentence = await request_model_change(
        session, clock, key="worker", model="claude-opus-9", effort="high"
    )
    assert "could not" in sentence
