"""The IT agent's run is read-only: write commands, local or over SSH, and file writes denied.

The request is the one the run service builds for the IT agent; the options and callbacks
are the ones the Claude adapter builds from it (plan §10, "IT agents cannot run a write
command").
"""

from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny, ToolPermissionContext

import labhq.roles  # noqa: F401  (registers the IT tools in the built-in registry)
from labhq.adapters import ClaudeAdapter, FakeAdapter, FakeScript, RunRequest
from labhq.adapters import default_registry as adapters
from labhq.memory import AgentMemory
from labhq.runs import RunService
from tests.it.conftest import DepartmentFactory
from tests.roles.conftest import Org

PERMISSION = ToolPermissionContext()
WRITES = [
    "rm -rf /var/log/old",
    "systemctl restart nginx",
    "apt upgrade -y",
    "df -h > /tmp/report",
    "ssh ro@nas.lan 'rm -rf /data/snapshots'",
    "ssh ro@nas.lan systemctl restart smbd",
    "ssh -o ProxyCommand='sh -c reboot' ro@nas.lan df",
    "sudo journalctl --vacuum-time=1d",
]
READS = ["df -h", "systemctl status nginx", "ssh ro@nas.lan df -h", "journalctl -u smbd -n 50"]


@pytest.fixture
async def request_(org: Org, department: DepartmentFactory, tmp_path: Path) -> RunRequest:
    agent_id = (await (await department()).tick()).agent_id
    assert agent_id is not None
    script = FakeScript()
    registry = adapters.copy()
    registry.register("fake", lambda: FakeAdapter(script), replace=True)
    service = RunService(
        org.sessions, clock=org.clock, registry=registry, memory=AgentMemory(tmp_path / "agents")
    )
    await service.execute(agent_id=agent_id, task_id=None, prompt="report", cwd=tmp_path)
    (request,) = script.requests
    return request


def options(request: RunRequest) -> Any:
    return ClaudeAdapter(cli_path=None, environ={}).options_for(request)


def bash(command: str) -> Any:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }


def test_the_it_run_never_bypasses_permissions(request_: RunRequest) -> None:
    built = options(request_)
    assert built.permission_mode == "default"
    assert built.can_use_tool is not None
    # Its engine tools are served and pre-approved: they change no machine.
    assert "mcp__labhq__add_rule" in built.allowed_tools
    assert "mcp__labhq__request_fix" in built.allowed_tools


@pytest.mark.parametrize("command", WRITES)
async def test_a_write_command_is_denied_by_the_hook_and_the_callback(
    request_: RunRequest, command: str
) -> None:
    built = options(request_)
    [matcher] = built.hooks["PreToolUse"]
    output: Any = await matcher.hooks[0](bash(command), None, {"signal": None})
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
    decision = await built.can_use_tool("Bash", {"command": command}, PERMISSION)
    assert isinstance(decision, PermissionResultDeny)


@pytest.mark.parametrize("command", READS)
async def test_a_read_command_goes_through(request_: RunRequest, command: str) -> None:
    built = options(request_)
    [matcher] = built.hooks["PreToolUse"]
    assert await matcher.hooks[0](bash(command), None, {"signal": None}) == {}
    decision = await built.can_use_tool("Bash", {"command": command}, PERMISSION)
    assert isinstance(decision, PermissionResultAllow)


@pytest.mark.parametrize("tool", ["Write", "Edit", "NotebookEdit"])
async def test_file_writes_are_denied(request_: RunRequest, tool: str) -> None:
    decision = await options(request_).can_use_tool(tool, {"file_path": "/etc/x"}, PERMISSION)
    assert isinstance(decision, PermissionResultDeny)
