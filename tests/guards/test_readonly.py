"""The read-only classifier, its hook and its `can_use_tool` callback (plan §2.2, §5 rule 2)."""

from typing import Any, cast

import pytest
from claude_agent_sdk import (
    HookContext,
    HookInput,
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
)

from labhq.guards.readonly import classify, deny_writes, read_only_permissions

ALLOWED = [
    "df -h",
    "free -m",
    "uptime",
    "ps aux",
    "ss -tlnp",
    "systemctl status nginx",
    "systemctl --no-pager is-active nginx",
    "systemctl is-failed nginx",
    "systemctl list-units --failed",
    "journalctl -u nginx --since today -n 50",
    "smartctl -a /dev/sda",
    "smartctl -H /dev/nvme0",
    "smartctl -i -d sat /dev/sdb",
    "docker ps -a",
    "docker inspect web",
    "docker logs --tail 100 web",
    "docker stats --no-stream",
    "cat /etc/os-release",
    "head -n 5 /var/log/syslog",
    "tail -n 20 /var/log/syslog",
    "ls -la /etc",
    "openssl x509 -noout -enddate -in /etc/ssl/cert.pem",
    "apt list --upgradable",
    "ps aux | grep nginx | head -n 3",
    "df -h 2>/dev/null",
    "journalctl -n 5 2>&1 | tail -n 2",
    "ssh web1 'systemctl status nginx'",
    "ssh -p 2222 web1 df -h",
    "env LC_ALL=C df -h",
    "timeout 5 docker ps",
    "bash -c 'uptime; free -m'",
    "/usr/bin/uptime",
    "LC_ALL=C ls",
    "cat $(ls /etc/hostname)",
]

DENIED = [
    ("rm -rf /tmp/x", "rm"),
    ("systemctl restart nginx", "restart"),
    ("systemctl --no-pager restart nginx", "restart"),
    ("apt upgrade -y", "upgrade"),
    ("echo hi | tee /etc/motd", "tee"),
    ("cat /etc/hosts > /tmp/hosts", "redirection"),
    ("cat /etc/hosts >> /tmp/hosts", "redirection"),
    ("df -h &> /tmp/df", "redirection"),
    ("sudo systemctl status nginx", "privilege"),
    ("sudo ls", "privilege"),
    ("ssh host 'systemctl restart x'", "restart"),
    ("ssh -o ProxyCommand='rm -rf x' host df", "local command"),
    ("ssh host", "nothing"),
    ("bash -c 'rm -rf x'", "rm"),
    ("bash deploy.sh", "nothing"),
    ("frobnicate --all", "frobnicate"),
    ("journalctl --vacuum-time=1d", "--vacuum-time"),
    ("journalctl --rotate", "--rotate"),
    ("journalctl --flush", "--flush"),
    ("smartctl -t long /dev/sda", "-t"),
    ("docker rm web", "rm"),
    ("docker stats", "--no-stream"),
    ("openssl x509 -in cert.pem -out copy.pem", "-noout"),
    ("ss -K dst 10.0.0.1", "-K"),
    ("env rm x", "rm"),
    ("timeout 5 rm x", "rm"),
    ("ls; rm x", "rm"),
    ("ps aux | xargs kill", "xargs"),
    ("cat $(rm x)", "rm"),
    ("$CMD status", "computed"),
    ("./ls", "system program"),
    ("env", "nothing"),
    ("ls >(rm x)", "redirection"),
]


@pytest.mark.parametrize("command", ALLOWED)
def test_read_commands_are_allowed(command: str) -> None:
    verdict = classify(command)
    assert verdict.allowed, verdict.reasons


@pytest.mark.parametrize(("command", "reason"), DENIED, ids=[command for command, _ in DENIED])
def test_writes_and_unknowns_are_denied(command: str, reason: str) -> None:
    verdict = classify(command)
    assert not verdict.allowed
    assert reason in "; ".join(verdict.reasons)


def bash_call(command: object) -> HookInput:
    return cast(
        HookInput,
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": command},
        },
    )


CONTEXT = cast(HookContext, {"signal": None})


async def test_the_hook_denies_a_write_command() -> None:
    output: Any = await deny_writes(bash_call("rm -rf /var/lib/x"), None, CONTEXT)
    decision = output["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"
    assert "rm" in decision["permissionDecisionReason"]


async def test_the_hook_lets_a_read_command_through() -> None:
    assert await deny_writes(bash_call("df -h"), None, CONTEXT) == {}


async def test_the_hook_denies_a_call_without_a_command() -> None:
    output: Any = await deny_writes(bash_call(None), None, CONTEXT)
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"


PERMISSION = ToolPermissionContext()


@pytest.mark.parametrize("tool", ["Write", "Edit", "NotebookEdit", "WebFetch", "mcp__x__y"])
async def test_can_use_tool_denies_tools_outside_the_read_only_list(tool: str) -> None:
    result = await read_only_permissions()(tool, {}, PERMISSION)
    assert isinstance(result, PermissionResultDeny)


@pytest.mark.parametrize("tool", ["Read", "Glob", "Grep", "mcp__labhq__whoami"])
async def test_can_use_tool_allows_read_tools_and_the_named_extras(tool: str) -> None:
    result = await read_only_permissions(["mcp__labhq__whoami"])(tool, {}, PERMISSION)
    assert isinstance(result, PermissionResultAllow)


async def test_can_use_tool_classifies_bash_too() -> None:
    can_use_tool = read_only_permissions()
    allowed = await can_use_tool("Bash", {"command": "uptime"}, PERMISSION)
    denied = await can_use_tool("Bash", {"command": "reboot"}, PERMISSION)
    assert isinstance(allowed, PermissionResultAllow)
    assert isinstance(denied, PermissionResultDeny)
