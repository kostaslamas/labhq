"""The `models` tools read the policy table back and only request a change."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.testclient import TestClient

from labhq.db.enums import ApprovalStatus
from labhq.db.models import Approval
from labhq.modelpolicy import load_policy
from tests.mcp.tools.test_tool_calls import assert_spoken, call, client

__all__ = ["client"]


def test_models_answers_from_the_table(client: TestClient) -> None:
    answer = call(client, "models")
    assert_spoken(answer)
    assert "Haiku 5.5 at medium effort for summary, check" in answer


async def test_a_change_is_requested_never_applied(
    session: AsyncSession, client: TestClient
) -> None:
    answer = call(client, "change_models", key="worker", model="claude-opus-5-5", effort="high")
    assert_spoken(answer)
    assert "passkey" in answer
    session.expire_all()
    assert (await load_policy(session)).rows["worker"].model == "claude-sonnet-5-5"
    pending = await session.scalar(
        select(func.count()).select_from(Approval).where(Approval.status == ApprovalStatus.PENDING)
    )
    assert pending == 1
