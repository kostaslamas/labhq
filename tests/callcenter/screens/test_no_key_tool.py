"""The Call Center stays read-only (ADR 0004): it holds no way to send a key."""

from pathlib import Path

import labhq.callcenter
import labhq.mcp
import labhq.mcp.tools
from labhq.mcp.tools.registry import default_registry

CALL_CENTER = Path(labhq.callcenter.__file__).parent
MCP = Path(labhq.mcp.__file__).parent


def sources() -> list[tuple[Path, str]]:
    return [(path, path.read_text()) for root in (CALL_CENTER, MCP) for path in root.rglob("*.py")]


def test_no_mcp_tool_sends_a_key() -> None:
    names = [spec.name for spec in default_registry]

    assert names
    assert not [name for name in names if "key" in name or "control" in name]


def test_neither_the_call_center_nor_the_mcp_server_can_reach_tmux_keys() -> None:
    files = sources()

    assert files
    offenders = [
        path.name
        for path, text in files
        if "send_keys" in text or "labhq.controlkeys" in text or "send_control_key" in text
    ]
    assert offenders == []
