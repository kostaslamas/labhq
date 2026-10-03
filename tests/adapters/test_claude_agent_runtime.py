"""What the Claude adapter builds for a working agent: prompt append, engine tools, read-only."""

from typing import Any

from claude_agent_sdk import HookMatcher, PermissionResultDeny, ToolPermissionContext

from labhq.adapters import AgentTool, ClaudeAdapter, RunRequest
from labhq.guards.readonly import deny_writes
from tests.adapters.stub_sdk import CLI_PATH

READ_ONLY = {"permission_mode": "read_only"}


async def reply(arguments: dict[str, Any]) -> str:
    return "ok"


def tool(name: str, *, read_only: bool = True) -> AgentTool:
    schema = {"type": "object", "properties": {}}
    return AgentTool(name, f"The {name} tool.", schema, reply, read_only=read_only)


def options_for(**fields: Any) -> Any:
    return ClaudeAdapter(cli_path=CLI_PATH, environ={}).options_for(
        RunRequest(prompt="hi", **fields)
    )


def test_the_append_rides_on_the_claude_code_preset() -> None:
    options = options_for(system_prompt_append="Role.\n\nStyle.")
    assert options.system_prompt == {
        "type": "preset",
        "preset": "claude_code",
        "append": "Role.\n\nStyle.",
    }


def test_no_append_keeps_the_previous_system_prompt() -> None:
    assert options_for().system_prompt is None


def test_agent_tools_join_the_built_in_tools() -> None:
    options = options_for(agent_tools=[tool("whoami"), tool("assign", read_only=False)])
    assert set(options.mcp_servers) == {"labhq"}
    assert options.allowed_tools == ["mcp__labhq__whoami", "mcp__labhq__assign"]
    # Built-in tools stay: a working agent keeps its shell and files.
    assert options.tools is None
    assert options.permission_mode == "bypassPermissions"


def test_a_runs_own_tools_still_replace_the_built_ins() -> None:
    options = options_for(tools=[tool("brief")], agent_tools=[tool("whoami")])
    assert options.tools == []
    assert options.allowed_tools == ["mcp__labhq__brief", "mcp__labhq__whoami"]


def test_read_only_never_bypasses_permissions_and_adds_both_layers() -> None:
    push_guard = HookMatcher(matcher="Bash", hooks=[])
    options = options_for(
        config=READ_ONLY,
        hooks={"PreToolUse": [push_guard]},
        agent_tools=[tool("whoami"), tool("assign", read_only=False)],
    )
    assert options.permission_mode != "bypassPermissions"
    assert options.permission_mode == "default"
    matchers = options.hooks["PreToolUse"]
    assert matchers[0] is push_guard
    assert [(m.matcher, m.hooks) for m in matchers[1:]] == [("Bash", [deny_writes])]
    assert options.can_use_tool is not None
    # A tool that writes is not served to a read-only agent, nor pre-approved.
    assert options.allowed_tools == ["mcp__labhq__whoami"]


async def test_read_only_callbacks_deny_a_write_command_and_file_writes() -> None:
    options = options_for(config=READ_ONLY)
    (matcher,) = options.hooks["PreToolUse"]
    hook_input: Any = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "systemctl restart nginx"},
    }
    output: Any = await matcher.hooks[0](hook_input, None, {"signal": None})
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
    context = ToolPermissionContext()
    for name in ("Write", "Edit"):
        decision = await options.can_use_tool(name, {"file_path": "/etc/x"}, context)
        assert isinstance(decision, PermissionResultDeny)
