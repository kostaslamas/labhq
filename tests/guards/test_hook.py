from typing import Any

from claude_agent_sdk import HookContext, HookInput

from labhq.guards import deny_publishing, push_guard_matcher

CONTEXT: HookContext = {"signal": None}


def pre_tool_use(tool_name: str, tool_input: dict[str, Any]) -> HookInput:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": "s",
        "transcript_path": "t",
        "cwd": "/w",
        "tool_name": tool_name,
        "tool_input": tool_input,
        "tool_use_id": "u",
    }


async def test_the_hook_denies_a_push_with_a_reason() -> None:
    output = await deny_publishing(
        pre_tool_use("Bash", {"command": "git -c x=y push"}), "u", CONTEXT
    )

    specific = output.get("hookSpecificOutput")
    assert specific is not None
    assert specific["hookEventName"] == "PreToolUse"
    assert specific.get("permissionDecision") == "deny"
    assert "git push" in str(specific.get("permissionDecisionReason"))


async def test_the_hook_stays_silent_for_ordinary_commands() -> None:
    output = await deny_publishing(pre_tool_use("Bash", {"command": "git status"}), "u", CONTEXT)

    assert output == {}


async def test_the_hook_ignores_other_tools() -> None:
    output = await deny_publishing(pre_tool_use("Read", {"file_path": "git push"}), "u", CONTEXT)

    assert output == {}


async def test_a_bash_call_without_a_command_string_is_denied() -> None:
    output = await deny_publishing(pre_tool_use("Bash", {"command": ["git", "push"]}), "u", CONTEXT)

    specific = output.get("hookSpecificOutput")
    assert specific is not None
    assert specific.get("permissionDecision") == "deny"


def test_the_matcher_guards_bash_with_the_hook() -> None:
    matcher = push_guard_matcher()

    assert matcher.matcher == "Bash"
    assert matcher.hooks == [deny_publishing]
