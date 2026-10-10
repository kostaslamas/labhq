"""Cost by model in integer micro-USD, and what the cheaper models saved."""

from sqlalchemy.ext.asyncio import AsyncSession

from labhq.clock import FakeClock
from labhq.db.models import CostEvent
from labhq.modelpolicy.report import cost_by_model
from tests.db.factories import project_agent_task


async def test_cost_is_grouped_by_model_and_summed_in_micros(
    session: AsyncSession, clock: FakeClock
) -> None:
    _, agent, _ = await project_agent_task(session, clock)
    for model, micros, tokens_in, tokens_out in [
        ("claude-haiku-5-5", 1_000, 1_000_000, 100_000),
        ("claude-haiku-5-5", 500, 0, 0),
        ("claude-sonnet-5-5", 20_000, 1_000_000, 100_000),
        (None, 7, 1, 1),
    ]:
        session.add(
            CostEvent(
                agent_id=agent.id,
                cost_micros=micros,
                model=model,
                input_tokens=tokens_in,
                output_tokens=tokens_out,
                created_at=clock.now(),
            )
        )
    await session.commit()

    rows = {row.model: row for row in await cost_by_model(session)}

    haiku = rows["claude-haiku-5-5"]
    assert (haiku.runs, haiku.cost_micros) == (2, 1_500)
    # 1M in + 100K out at the worker model's list price is 3.0 USD.
    assert haiku.reference_micros == 3_000_000 and haiku.saved_micros == 3_000_000 - 1_500
    assert rows["claude-sonnet-5-5"].saved_micros == 3_000_000 - 20_000
    assert rows["unknown"].reference_micros is None
    assert all(isinstance(row.cost_micros, int) for row in rows.values())
