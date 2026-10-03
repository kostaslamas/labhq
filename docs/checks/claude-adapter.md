# Manual check: the Claude adapter against a real login

CI proves the adapter contract against the fake adapter and against the Claude adapter with
`ClaudeSDKClient` stubbed (`tests/adapters/test_contract.py`). Only a real Claude Code
login can prove the same contract end to end, so it is a manual check, run on a developer
machine. Tests never do this (CONTRIBUTING.md §7).

## What it proves

The same checks as CI, from `labhq.adapters.contract`, on the adapter the default registry
builds for `claude`:

| Check | Prompt | Passes when |
|---|---|---|
| `completes` | Reply with the single word OK. | Events stream, the last is the result, it maps to `succeeded`, a session id is reported, cost is not negative |
| `interrupt` | Run `sleep 30` with the Bash tool, then reply DONE. | `interrupt()` on the first assistant event ends the turn with a result that maps to `interrupted` (`terminal_reason` `aborted_streaming` or `aborted_tools`) |
| `resume` | Remember the codeword AURORA-7 ..., then What was the codeword? | The second run, started with `resume=<first session id>`, succeeds and keeps the session id |

## Before you run it

- Claude Code is installed and logged in: `claude --version` prints a version and
  `claude` starts without asking you to log in. labhq does not check or read the login;
  the binary uses its own (ADR 0001).
- Billing: with `ANTHROPIC_API_KEY` set, the run is billed to that key. Without it, it uses
  your subscription login. The three checks cost a few cents (the Phase 0 spike measured
  0.0097 to 0.0384 USD per run with Haiku).
- The binary is pinned: set `LABHQ_CLI_PATH` to the binary you want, or leave it unset to
  use the `claude` found on `PATH`. The SDK's bundled build is never used.
- The checks run in a fresh temporary directory, with `setting_sources=[]`, so your own
  hooks and settings stay out. `max_turns` is 4 and the model is Claude Code's default.

## Run it

```sh
uv sync
uv run python -m labhq.adapters.contract claude
```

Each check prints `PASS` or `FAIL` with its cost, then the total. The exit status is 0 only
when every check passed.

## Recorded results

Record every run here: date, `claude --version`, `claude-agent-sdk` version, billing path
(subscription or API key), model, the output, and who ran it.

| Date | Claude Code | SDK | Billing | Result | Total cost | Run by |
|---|---|---|---|---|---|---|
| 2026-10-03 | 2.1.288 | 0.2.163 | subscription | PASS completes ($0.0331), PASS interrupt ($0.0010), PASS resume ($0.0987) | $0.1327 | owner's machine |
