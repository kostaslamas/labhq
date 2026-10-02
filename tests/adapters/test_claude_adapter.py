"""The Claude adapter's options and stream translation, with the SDK client stubbed."""

from pathlib import Path

import pytest
from claude_agent_sdk import HookMatcher

from labhq.adapters import AdapterError, ClaudeAdapter, RunRequest
from labhq.adapters.claude import default_cli_path
from labhq.adapters.contract import run_once
from tests.adapters.stub_sdk import CLI_PATH, MODEL, StubScript, stub_claude


def test_options_pin_the_cli_and_load_no_settings(tmp_path: Path) -> None:
    options = ClaudeAdapter(cli_path=CLI_PATH, environ={}).options_for(
        RunRequest(prompt="hi", cwd=tmp_path)
    )
    assert options.cli_path == CLI_PATH
    assert options.setting_sources == []
    assert options.cwd == tmp_path
    assert options.resume is None


def test_permission_mode_defaults_to_bypass() -> None:
    options = ClaudeAdapter(cli_path=CLI_PATH, environ={}).options_for(RunRequest(prompt="hi"))
    assert options.permission_mode == "bypassPermissions"


def test_agent_config_sets_mode_model_and_turns_and_ignores_other_keys() -> None:
    config = {"permission_mode": "default", "model": MODEL, "max_turns": 3, "timeout_s": 600}
    options = ClaudeAdapter(cli_path=CLI_PATH, environ={}).options_for(
        RunRequest(prompt="hi", config=config)
    )
    assert (options.permission_mode, options.model, options.max_turns) == ("default", MODEL, 3)


def test_an_unknown_permission_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="permission_mode"):
        ClaudeAdapter(cli_path=CLI_PATH, environ={}).options_for(
            RunRequest(prompt="hi", config={"permission_mode": "yolo"})
        )


def test_resume_and_caller_hooks_are_passed_through() -> None:
    matcher = HookMatcher(matcher="Bash", hooks=[])
    options = ClaudeAdapter(cli_path=CLI_PATH, environ={}).options_for(
        RunRequest(prompt="hi", resume_session_id="abc", hooks={"PreToolUse": [matcher]})
    )
    assert options.resume == "abc"
    assert options.hooks == {"PreToolUse": [matcher]}


def test_the_installed_binary_is_preferred_over_the_bundled_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/claude")
    assert default_cli_path(None) == Path("/usr/local/bin/claude")
    assert default_cli_path(CLI_PATH) == CLI_PATH


async def test_stream_becomes_events_and_a_result(tmp_path: Path) -> None:
    script = StubScript()
    events, result = await run_once(stub_claude(script)(), RunRequest(prompt="hi", cwd=tmp_path))
    assert [event.kind for event in events] == ["system", "assistant", "result"]
    assert events[1].payload["content"] == [{"text": "OK"}]
    assert result.subtype == "success"
    assert result.session_id == "stub-session-1"
    assert result.cost_usd == 0.0097
    assert result.model == MODEL
    assert result.usage["input_tokens"] == 410
    assert script.queries == ["hi"]
    assert script.disconnects == 1


async def test_interrupt_reports_the_sdk_abort(tmp_path: Path) -> None:
    script = StubScript(wait_for_interrupt=True)
    adapter = stub_claude(script)()
    await adapter.start(RunRequest(prompt="sleep", cwd=tmp_path))
    await adapter.interrupt()
    kinds = [event.kind async for event in adapter.events()]
    result = adapter.result()
    assert kinds[-1] == "result"
    assert (result.subtype, result.terminal_reason) == (
        "error_during_execution",
        "aborted_streaming",
    )


async def test_send_queries_the_running_conversation(tmp_path: Path) -> None:
    script = StubScript()
    adapter = stub_claude(script)()
    await adapter.start(RunRequest(prompt="first", cwd=tmp_path))
    await adapter.send("also this")
    assert script.queries == ["first", "also this"]


async def test_a_stream_without_a_result_is_an_error(tmp_path: Path) -> None:
    adapter = stub_claude(StubScript(result_overrides=None))()
    with pytest.raises(AdapterError, match="without a result"):
        await run_once(adapter, RunRequest(prompt="hi", cwd=tmp_path))


async def test_an_unknown_message_type_is_kept_under_its_class_name(tmp_path: Path) -> None:
    class Novel:
        pass

    adapter = stub_claude(StubScript(messages=[Novel()]))()
    events, _ = await run_once(adapter, RunRequest(prompt="hi", cwd=tmp_path))
    assert events[0].kind == "Novel"


async def test_one_adapter_instance_serves_one_run(tmp_path: Path) -> None:
    adapter = stub_claude(StubScript())()
    await adapter.start(RunRequest(prompt="hi", cwd=tmp_path))
    with pytest.raises(AdapterError, match="one run"):
        await adapter.start(RunRequest(prompt="again", cwd=tmp_path))
