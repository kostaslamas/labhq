"""The table is stored with the defaults, and an unknown model or effort is refused on save."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.clock import FakeClock
from labhq.modelpolicy import PolicyError, load_policy, save_policy
from labhq.modelpolicy.catalog import BY_ID, estimate_micros


def test_catalog_ids_carry_no_date_suffix() -> None:
    assert set(BY_ID) == {
        "claude-opus-5-5",
        "claude-sonnet-5-5",
        "claude-haiku-5-5",
        "claude-haiku-4-5",
    }


def test_catalog_prices_are_integer_micros() -> None:
    assert estimate_micros("claude-haiku-5-5", 1_000_000, 1_000_000) == 600_000
    assert estimate_micros("claude-sonnet-5-5", 1_000_000, 1_000_000) == 12_000_000
    assert estimate_micros("not-a-model", 1, 1) is None


async def test_defaults_match_the_issue(session: AsyncSession) -> None:
    rows = (await load_policy(session)).rows
    for key in ("ceo", "manager", "head", "lead"):
        assert (rows[key].model, rows[key].effort) == ("claude-sonnet-5-5", "high")
    for key in ("worker", "it", "project_analysis"):
        assert (rows[key].model, rows[key].effort) == ("claude-sonnet-5-5", "medium")
    for key in ("summary", "check"):
        assert (rows[key].model, rows[key].effort) == ("claude-haiku-5-5", "medium")
        # Adaptive thinking spends output tokens too: the cap leaves room for the answer.
        assert (rows[key].max_output_tokens or 0) >= 8_000


async def test_a_saved_row_is_kept_and_the_rest_stay_default(
    session: AsyncSession, clock: FakeClock
) -> None:
    await save_policy(session, clock, {"worker": {"model": "claude-opus-5-5", "effort": "high"}})
    rows = (await load_policy(session)).rows
    assert rows["worker"].model == "claude-opus-5-5"
    assert rows["summary"].model == "claude-haiku-5-5"


@pytest.mark.parametrize(
    "rows",
    [
        {"worker": {"model": "claude-sonnet-5-5-20260101", "effort": "low"}},
        {"worker": {"model": "gpt-9", "effort": "low"}},
        {"worker": {"model": "claude-opus-5-5", "effort": "extreme"}},
        {"janitor": {"model": "claude-opus-5-5", "effort": "low"}},
    ],
)
async def test_unknown_input_is_rejected_and_nothing_is_saved(
    session: AsyncSession, clock: FakeClock, rows: dict[str, object]
) -> None:
    with pytest.raises(PolicyError):
        await save_policy(session, clock, rows)
    assert (await load_policy(session)).rows["worker"].model == "claude-sonnet-5-5"
