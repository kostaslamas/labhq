"""Experiment 4: can_use_tool may block 65 s (a human approving later)."""

import asyncio

from claude_agent_sdk import ClaudeSDKClient, PermissionResultAllow

from .common import Outcome, Stopwatch, base_options, cleanup, run_turn, tmpdir

WAIT_S = 65


async def run() -> Outcome:
    out = Outcome("strict_approval_wait")
    work = tmpdir("approval")
    calls: list[str] = []

    async def approve_later(tool_name, tool_input, context):
        calls.append(tool_name)
        await asyncio.sleep(WAIT_S)
        return PermissionResultAllow()

    try:
        # Plain `echo approved` is auto-allowed as read-only in default mode and
        # never reaches the callback, so the command writes a file instead.
        # No allowed_tools: that would auto-approve Bash and bypass the callback.
        opts = base_options(work, permission_mode="default", can_use_tool=approve_later)
        with Stopwatch() as sw:
            async with ClaudeSDKClient(opts) as client:
                text, res = await run_turn(
                    client,
                    (
                        "Run this exact shell command with Bash and show its output: "
                        "echo approved > approved.txt && cat approved.txt"
                    ),
                )
        out.elapsed_s, out.cost_usd = sw.elapsed, res.total_cost_usd or 0.0
        out.passed = "approved" in text.lower() and out.elapsed_s >= WAIT_S
        out.notes += [
            f"can_use_tool invoked for: {calls}",
            f"is_error={res.is_error}, denials={len(res.permission_denials or [])}",
            f"agent reply: {text.strip()[:200]!r}",
        ]
    finally:
        cleanup(work)
    return out
