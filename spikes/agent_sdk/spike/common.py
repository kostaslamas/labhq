"""Shared helpers for the spike experiments."""

import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, ResultMessage
from claude_agent_sdk.types import AssistantMessage, TextBlock

MODEL = "claude-haiku-4-5-20251001"


@dataclass
class Outcome:
    name: str
    passed: bool = False
    elapsed_s: float = 0.0
    cost_usd: float = 0.0
    notes: list[str] = field(default_factory=list)


def base_options(cwd: Path, **overrides) -> ClaudeAgentOptions:
    """Options shared by every experiment.

    setting_sources=[] keeps the operator's personal hooks and rules out of the
    run so results depend on the SDK alone. cli_path pins the system CLI rather
    than the copy bundled in the wheel (they can differ by a patch version).
    """
    params = {
        "model": MODEL,
        "cwd": str(cwd),
        "max_turns": 4,
        "setting_sources": [],
        "cli_path": shutil.which("claude"),
    }
    params.update(overrides)
    return ClaudeAgentOptions(**params)


def tmpdir(prefix: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=f"spike-{prefix}-"))


def git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    )
    return done.stdout


async def run_turn(client: ClaudeSDKClient, prompt: str) -> tuple[str, ResultMessage]:
    """Send one prompt and drain the stream; return (assistant text, result)."""
    await client.query(prompt)
    text: list[str] = []
    result = None
    async for msg in client.receive_response():
        if isinstance(msg, AssistantMessage):
            text += [b.text for b in msg.content if isinstance(b, TextBlock)]
        elif isinstance(msg, ResultMessage):
            result = msg
    assert result is not None, "stream ended without a ResultMessage"
    return "\n".join(text), result


class Stopwatch:
    def __enter__(self):
        self.start = time.monotonic()
        return self

    def __exit__(self, *exc):
        self.elapsed = time.monotonic() - self.start


def cleanup(*paths: Path) -> None:
    for p in paths:
        shutil.rmtree(p, ignore_errors=True)
