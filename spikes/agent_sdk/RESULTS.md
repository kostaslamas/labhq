# Agent SDK spike results

- Date: 2026-10-02
- `claude-agent-sdk` (Python): 0.2.163 (wheel bundles CLI 2.1.286; runs pinned to the system CLI via `cli_path`)
- Claude Code CLI: 2.1.287
- Model: `claude-haiku-4-5-20251001`; auth: existing local login
- Common options: `setting_sources=[]` (no user hooks or settings leak in), temp `cwd`, `max_turns` 2-4

| Experiment | Result | Elapsed | total_cost_usd |
|---|---|---|---|
| hook_blocks_push | PASS | 6.1 s | 0.0384 |
| interrupt | PASS | 5.0 s | 0.0097 |
| resume | PASS | 5.5 s | 0.0210 |
| strict_approval_wait | PASS (second attempt) | 71.3 s | 0.0172 |

Total for the passing runs: 0.0863 USD. One failed first attempt of
strict_approval_wait cost a further 0.0398 USD (0.1261 USD overall).

## 1. hook_blocks_push

`permission_mode="bypassPermissions"` plus a `HookMatcher(matcher="Bash")` PreToolUse hook
returning `hookSpecificOutput.permissionDecision="deny"` for `git push` / `gh pr merge`.
- The hook fired for `git push origin main`; the local bare remote had no refs afterwards.
- The deny is honoured even in bypass mode, so a hook is a valid hard guard.
- `ResultMessage.permission_denials` recorded 1 entry; the agent reported the policy reason and stopped.
- Caveat: substring matching is trivially evadable (`git -c x=y push`, aliases, scripts). Production
  needs a parsed-command check, and ideally a network/credential-level guard as well.

## 2. interrupt

`client.query()`, consume `receive_response()` in a task, `await client.interrupt()` at 5 s.
- The turn ended at 5.0 s (sleep was 30 s), no DONE.
- The stream still ends with a `ResultMessage`, but `subtype="error_during_execution"`,
  `is_error=True`, `terminal_reason="aborted_streaming"`. The orchestrator must treat this as
  "interrupted", not as a failure.
- The client stays usable afterwards (not exercised further here).

## 3. resume

Two separate `ClaudeSDKClient` instances; the second uses `resume=<ResultMessage.session_id>`.
- Reply to "What was the codeword?" was "The codeword is **AURORA-7**."
- The resumed session kept the same session id. Both sessions need the same `cwd`
  (sessions are stored per project directory).

## 4. strict_approval_wait

Default permission mode, `can_use_tool` callback sleeping 65 s then returning `PermissionResultAllow()`.
- Passed: output contained "approved", elapsed 71.3 s, callback invoked once for `Bash`.
- Surprise 1 (our bug in the first attempt): plain `echo approved` is auto-allowed as a read-only
  command in default mode, so `can_use_tool` was never called (run took 5 s, FAIL). The experiment now
  runs `echo approved > approved.txt && cat approved.txt`, which does require permission. Implication:
  an approval gate must not assume every Bash call reaches the callback; read-only commands bypass it.
- Surprise 2: the documented dummy-PreToolUse-hook workaround was not needed. `ClaudeSDKClient`
  always uses streaming input, and a 65 s callback wait worked without it. The workaround applies
  to the one-shot `query()` function with a plain string prompt; not tested here.
- The 65 s wait exceeded the default 60 s hook timeout without issue, because `can_use_tool` is a
  control-protocol request, not a hook. No timeout on the permission request was observed up to 65 s.
- Do not pass `allowed_tools=["Bash"]` in this mode: it auto-approves and shadows the callback
  (the SDK emits a warning for this).

## Plan impact

- Hooks are enforceable guards under bypassPermissions; the orchestrator can rely on them for
  publish blocking, but the matcher must be stricter than substring checks.
- Approval gates via `can_use_tool` can wait on humans for at least 65 s; longer waits are untested.
- Interrupts surface as an error-subtype result; map `terminal_reason="aborted_streaming"` to a state.
- Pin `cli_path` explicitly: the wheel bundles a different CLI patch version than the system one.
