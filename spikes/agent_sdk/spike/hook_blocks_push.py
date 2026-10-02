"""Experiment 1: a PreToolUse hook denies `git push` under bypassPermissions."""

from claude_agent_sdk import ClaudeSDKClient, HookMatcher

from .common import Outcome, Stopwatch, base_options, cleanup, git, run_turn, tmpdir

BLOCKED = ("git push", "gh pr merge")


async def run() -> Outcome:
    out = Outcome("hook_blocks_push")
    work, remote = tmpdir("work"), tmpdir("remote")
    fired: list[str] = []

    async def deny_publish(input_data, tool_use_id, context):
        cmd = input_data.get("tool_input", {}).get("command", "")
        if any(b in cmd for b in BLOCKED):
            fired.append(cmd)
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": "Publishing is blocked by policy.",
                }
            }
        return {}

    try:
        git(remote, "init", "--bare", "-q")
        git(work, "init", "-q", "-b", "main")
        git(work, "config", "user.email", "spike@example.invalid")
        git(work, "config", "user.name", "Spike")
        (work / "a.txt").write_text("hello\n")
        git(work, "add", ".")
        git(work, "commit", "-q", "-m", "init")
        git(work, "remote", "add", "origin", str(remote))

        opts = base_options(
            work,
            permission_mode="bypassPermissions",
            allowed_tools=["Bash"],
            hooks={"PreToolUse": [HookMatcher(matcher="Bash", hooks=[deny_publish])]},
        )
        with Stopwatch() as sw:
            async with ClaudeSDKClient(opts) as client:
                text, res = await run_turn(
                    client,
                    "Run exactly this shell command and report its output: git push origin main",
                )
        refs = git(remote, "for-each-ref").strip()
        out.elapsed_s, out.cost_usd = sw.elapsed, res.total_cost_usd or 0.0
        out.passed = bool(fired) and refs == ""
        out.notes += [
            f"hook fired with deny: {bool(fired)} (commands: {fired})",
            f"bare remote refs after run: {refs or 'none'}",
            f"permission_denials in result: {len(res.permission_denials or [])}",
            f"agent reply: {text.strip()[:200]!r}",
        ]
    finally:
        cleanup(work, remote)
    return out
