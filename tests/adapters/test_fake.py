"""The fake adapter is deterministic and does what its script says."""

import pytest

from labhq.adapters import AdapterError, AdapterEvent, FakeAdapter, FakeScript, RunRequest
from labhq.adapters.contract import run_once


async def test_default_script_is_a_short_successful_run() -> None:
    events, result = await run_once(FakeAdapter(), RunRequest(prompt="hi"))
    assert [event.kind for event in events] == ["system", "assistant", "result"]
    assert (result.subtype, result.is_error, result.cost_usd) == ("success", False, 0.0125)


async def test_the_same_script_gives_the_same_run() -> None:
    first = await run_once(FakeAdapter(FakeScript()), RunRequest(prompt="hi"))
    second = await run_once(FakeAdapter(FakeScript()), RunRequest(prompt="hi"))
    assert first == second


async def test_scripted_events_cost_and_result_are_reported() -> None:
    script = FakeScript(
        events=[AdapterEvent("tool", {"name": "Bash"})],
        subtype="error_max_turns",
        is_error=True,
        terminal_reason="max_turns",
        cost_usd=0.5,
    )
    events, result = await run_once(FakeAdapter(script), RunRequest(prompt="hi"))
    assert events[0] == AdapterEvent("tool", {"name": "Bash"})
    assert (result.subtype, result.terminal_reason, result.cost_usd) == (
        "error_max_turns",
        "max_turns",
        0.5,
    )


async def test_a_scripted_failure_is_raised_and_the_adapter_still_closes() -> None:
    script = FakeScript(fail_with=RuntimeError("boom"))
    with pytest.raises(RuntimeError, match="boom"):
        await run_once(FakeAdapter(script), RunRequest(prompt="hi"))
    assert script.closes == 1


async def test_requests_and_inputs_are_recorded() -> None:
    script = FakeScript()
    adapter = FakeAdapter(script)
    request = RunRequest(prompt="hi", resume_session_id="s-1")
    await adapter.start(request)
    await adapter.send("more")
    assert script.requests == [request]
    assert script.inputs == ["more"]


async def test_result_is_unavailable_before_the_stream_ends() -> None:
    adapter = FakeAdapter()
    await adapter.start(RunRequest(prompt="hi"))
    with pytest.raises(AdapterError, match="no result"):
        adapter.result()


async def test_events_need_a_started_run() -> None:
    with pytest.raises(AdapterError, match="start"):
        [event async for event in FakeAdapter().events()]
