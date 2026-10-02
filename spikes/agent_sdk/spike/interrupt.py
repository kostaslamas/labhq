"""Experiment 2: client.interrupt() ends a turn stuck in `sleep 30`."""

import asyncio
import time

from claude_agent_sdk import ClaudeSDKClient, ResultMessage
from claude_agent_sdk.types import AssistantMessage, TextBlock

from .common import Outcome, base_options, cleanup, tmpdir

PROMPT = "Run `sleep 30` with the Bash tool, then reply with the single word DONE."


async def run() -> Outcome:
    out = Outcome("interrupt")
    work = tmpdir("interrupt")
    text: list[str] = []
    result = None
    try:
        opts = base_options(
            work, permission_mode="bypassPermissions", allowed_tools=["Bash"]
        )
        async with ClaudeSDKClient(opts) as client:
            start = time.monotonic()
            await client.query(PROMPT)

            async def drain():
                nonlocal result
                async for msg in client.receive_response():
                    if isinstance(msg, AssistantMessage):
                        text.extend(
                            b.text for b in msg.content if isinstance(b, TextBlock)
                        )
                    elif isinstance(msg, ResultMessage):
                        result = msg

            task = asyncio.create_task(drain())
            await asyncio.sleep(5)
            interrupted_at = time.monotonic() - start
            await client.interrupt()
            await asyncio.wait_for(task, timeout=40)
            out.elapsed_s = time.monotonic() - start
        out.cost_usd = (result.total_cost_usd or 0.0) if result else 0.0
        joined = " ".join(text)
        out.passed = out.elapsed_s < 20 and "DONE" not in joined
        out.notes += [
            f"interrupt() sent at {interrupted_at:.1f}s, turn ended at {out.elapsed_s:.1f}s",
            (
                f"result subtype={getattr(result, 'subtype', None)} "
                f"terminal_reason={getattr(result, 'terminal_reason', None)} "
                f"is_error={getattr(result, 'is_error', None)}"
            ),
            f"assistant text after interrupt: {joined[:200]!r}",
        ]
    finally:
        cleanup(work)
    return out
