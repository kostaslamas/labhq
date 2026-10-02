"""Experiment 3: a second client resumes a session by id and recalls state."""

from claude_agent_sdk import ClaudeSDKClient

from .common import Outcome, Stopwatch, base_options, cleanup, run_turn, tmpdir


async def run() -> Outcome:
    out = Outcome("resume")
    work = tmpdir("resume")
    try:
        with Stopwatch() as sw:
            async with ClaudeSDKClient(base_options(work, max_turns=2)) as c1:
                t1, r1 = await run_turn(
                    c1, "Remember the codeword AURORA-7 and reply OK."
                )
            async with ClaudeSDKClient(
                base_options(work, max_turns=2, resume=r1.session_id)
            ) as c2:
                t2, r2 = await run_turn(c2, "What was the codeword?")
        out.elapsed_s = sw.elapsed
        out.cost_usd = (r1.total_cost_usd or 0.0) + (r2.total_cost_usd or 0.0)
        out.passed = "AURORA-7" in t2
        out.notes += [
            f"session 1 reply: {t1.strip()[:80]!r}",
            f"session 2 reply: {t2.strip()[:120]!r}",
            f"session id kept on resume: {r2.session_id == r1.session_id}",
        ]
    finally:
        cleanup(work)
    return out
