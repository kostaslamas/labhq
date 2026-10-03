# Manual check: the Phase 1 demo with the real adapter

CI runs `labhq demo` with the fake adapter (`tests/cli/test_demo.py`). The fake writes and
commits a file itself, so CI proves everything around the worker (scheduler, worktree,
checkout, cost row, push approval and the push after approval) but not that a real agent
does the work. Only a real Claude Code login can prove that, so it is a manual check, run on
a developer machine before the `v0.1.0-alpha.1` tag (plan §10, CONTRIBUTING.md §7).

## What it proves

1. One project, one manager and one worker (reporting to the manager) are created from the
   CLI, and a task assigned to the worker is run by one scheduler pass.
2. The worker, Claude Code on the owner's login, works in the task's worktree under the
   push guard and commits there: the task branch has at least one commit.
3. The run is recorded: `runs.status` is `succeeded` and one `cost_events` row carries the
   cost in micro-USD and the token counts.
4. The engine, not the agent, asks to push: a `push` approval is `pending`, and nothing has
   reached the remote.
5. `labhq approvals approve <id>` pushes exactly the pinned commit to the remote.

## Before you run it

- Claude Code is installed and logged in: `claude --version` prints a version and `claude`
  starts without asking you to log in. labhq never reads the login (ADR 0001).
- Billing: with `ANTHROPIC_API_KEY` set, the run is billed to that key; without it, to your
  subscription. One demo run costs cents.
- Pin the binary: set `LABHQ_CLI_PATH` to the installed Claude Code, or leave it unset to use
  the `claude` on `PATH`. The SDK's bundled build is never used.
- Use a scratch data directory, so the demo's rows are the only ones:
  `export LABHQ_DATA_DIR="$(mktemp -d)/labhq"`.
- Optional: install `rtk` first. Without it the run records an `rtk_missing` warning event,
  which is expected and does not fail the check.

## Run it

```sh
uv sync
uv run labhq demo --adapter claude
```

With no `--repo`, the demo builds a sandbox under `$LABHQ_DATA_DIR/demo/`: a repository with
one commit and a local bare `origin`. It prints the branch, the commit, the `cost_events`
row and the pending approval, then the command to approve it. It exits non-zero if the run
ends without a cost row or without a commit to push; the message carries the run's exit
details.

Then check and approve:

```sh
uv run labhq approvals list
git -C "$LABHQ_DATA_DIR"/demo/*/origin.git for-each-ref     # no labhq/task-* branch yet
uv run labhq approvals approve <id>
git -C "$LABHQ_DATA_DIR"/demo/*/origin.git for-each-ref     # the branch, at the printed commit
```

## Pass condition

All five points above hold: the demo exits 0, `cost_micros` is above zero, the remote has no
task branch before the approval, and after it has the task branch at exactly the printed
commit.

## Recorded results

Record every run here: date, `claude --version`, `claude-agent-sdk` version, billing path,
model, the demo's output (branch, commit, cost row, approval) and the push result.

| Date | labhq commit | Claude Code | SDK | Billing | Model | Cost | Branch and commit | Pushed after approval | Run by |
|---|---|---|---|---|---|---|---|---|---|
| _not run yet_ | | | | | | | | | owner |

## Index of Phase 1 manual checks

Every Phase 1 behaviour that only a real model can prove, and where its result is recorded.
The `v0.1.0-alpha.1` tag waits until each has a recorded result.

| Check | Proves | Result recorded in |
|---|---|---|
| [Claude adapter](claude-adapter.md) | The adapter contract (complete, interrupt, resume) against a real login | `claude-adapter.md`, Recorded results |
| [Push guard](push-guard.md) | A real agent cannot push from its worktree, with or without the hook | `push-guard.md`, Result |
| [`rtk` A/B](rtk-ab.md) | The `rtk` hook lowers a worker run's input tokens with the same answer | `rtk-ab.md`, Result |
| Phase 1 demo (this file) | The demo end to end with a real worker, and the push after approval | This file, Recorded results |
