"""The run service applies the policy: Claude kinds get the model, others ignore the row."""

import logging
from typing import Any

import pytest

from labhq.modelpolicy import save_policy
from tests.runs.conftest import World
from tests.runs.helpers import stored_run, use_adapter


async def test_a_claude_run_gets_the_role_row_and_records_it(world: World) -> None:
    await use_adapter(world, "claude")
    run = await world.service.execute(agent_id=world.agent_id, task_id=world.task_id, prompt="x")
    options = world.claude.options[-1]
    assert (options.model, options.effort) == ("claude-sonnet-5-5", "medium")
    assert (await stored_run(world, run.id)).model == "claude-sonnet-5-5"


async def test_a_task_kind_row_is_cheaper_than_the_role_row(world: World) -> None:
    await use_adapter(world, "claude")
    run = await world.service.execute(
        agent_id=world.agent_id, task_id=None, prompt="x", task_kind="summary"
    )
    options = world.claude.options[-1]
    assert (options.model, options.effort) == ("claude-haiku-5-5", "medium")
    assert (await stored_run(world, run.id)).model == "claude-haiku-5-5"
    assert options.env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "16000"


async def test_the_request_beats_the_agent_override(world: World) -> None:
    await use_adapter(world, "claude", {"model": "claude-opus-5-5"})
    await world.service.execute(agent_id=world.agent_id, task_id=None, prompt="x")
    assert world.claude.options[-1].model == "claude-opus-5-5"
    await world.service.execute(
        agent_id=world.agent_id, task_id=None, prompt="x", model="claude-haiku-4-5"
    )
    assert world.claude.options[-1].model == "claude-haiku-4-5"


async def test_an_edited_table_changes_the_next_run(world: World) -> None:
    await use_adapter(world, "claude")
    async with world.sessions() as db:
        await save_policy(
            db, world.clock, {"worker": {"model": "claude-opus-5-5", "effort": "high"}}
        )
    await world.service.execute(agent_id=world.agent_id, task_id=None, prompt="x")
    assert world.claude.options[-1].model == "claude-opus-5-5"


async def test_another_kind_ignores_the_row_and_logs_it(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="labhq.modelpolicy.run"):
        run = await world.service.execute(
            agent_id=world.agent_id, task_id=None, prompt="x", task_kind="summary"
        )
    request: Any = world.fake.requests[-1]
    assert (request.model, request.effort) == (None, None)
    assert "takes no model" in caplog.text
    # The run still records the model the adapter reported.
    assert (await stored_run(world, run.id)).model == "fake-model"


async def test_an_unusable_row_falls_back_to_the_next(world: World) -> None:
    from datetime import timedelta

    from labhq.db.models import UsageReading

    await use_adapter(world, "claude")
    async with world.sessions() as db:
        db.add(
            UsageReading(
                agent_id=world.agent_id,
                agent_kind="claude",
                source="test",
                unit="percent",
                value=100,
                window="seven_day_haiku",
                resets_at=world.clock.now() + timedelta(days=1),
                created_at=world.clock.now(),
            )
        )
        await db.commit()
    await world.service.execute(
        agent_id=world.agent_id, task_id=None, prompt="x", task_kind="summary"
    )
    assert world.claude.options[-1].model == "claude-sonnet-5-5"
