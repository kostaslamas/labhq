# Manual check: the Phase 1 demo with a real agent

Acceptance criterion of issue #13 and the Phase 1 demo of plan §10: one project, one manager,
one worker. Task → worktree branch with a commit → cost recorded → push needs approval.

`tests/cli/` proves the same flow on the fake adapter and a local bare remote. Only a real
Claude Code login can prove that a real worker commits in its worktree and that the engine
records its real cost, so this is a manual check, run on a developer machine before the
`v0.1.0-alpha.1` tag. Tests never do this (CONTRIBUTING.md §7).

## What it proves

1. `labhq demo --adapter claude` creates the project, a manager and a worker that reports
   to it, assigns the worker a task and runs it in the task's worktree with the push guard
   (and the `rtk` hook when `rtk` is on `PATH`).
2. The worker commits on `labhq/task-<id>-…`; the branch is at least one commit ahead of
   `main`.
3. The run's `cost_events` row holds the SDK's cost in integer micro-USD and non-zero token
   counts.
4. A `push` approval waits in `pending`, and the bare remote has no task branch yet.
5. `labhq approvals approve <id>` publishes exactly the pinned commit to the remote.

## Setup

- `uv sync` in the repository root; `labhq` runs from the checkout (`uv run labhq`).
- A Claude Code login on this machine (`claude` works in a terminal), or `ANTHROPIC_API_KEY`
  in the environment. labhq never reads the login itself (ADR 0001).
- `LABHQ_CLI_PATH` pointing at the installed Claude Code binary; the SDK wheel bundles a
  different build (spikes/agent_sdk/RESULTS.md).
- A scratch data directory, so the check never touches your real labhq database.

```sh
export LABHQ_DATA_DIR="$(mktemp -d)/labhq"
export LABHQ_CLI_PATH="$(command -v claude)"
claude --version
uv run python -c "import claude_agent_sdk; print(claude_agent_sdk.__version__)"
```

## Steps

1. Run the demo with the real adapter. The worker has a $1 monthly budget and at most 10
   turns (`labhq.cli.demo`).

   ```sh
   uv run labhq demo --adapter claude
   ```

   Expect, in order: the project, `manager: agent 1; worker: agent 2 reports to 1`, the
   task, `run 1: succeeded (agent 2, task 1, …)`, one
   `cost_events` line, `branch: labhq/task-1-add-a-hello-file`, `commit: <sha>` and
   `approval 1: push [heavy] pending`. The command exits 0.

2. Inspect the branch and the remote before approving.

   ```sh
   cd "$LABHQ_DATA_DIR/demo/demo/project"
   git log --oneline main..labhq/task-1-add-a-hello-file   # at least one commit
   git show --stat labhq/task-1-add-a-hello-file           # HELLO.md
   git --git-dir ../remote.git branch --list 'labhq/*'     # empty
   cd -
   ```

3. Inspect the cost row.

   ```sh
   sqlite3 "$LABHQ_DATA_DIR/labhq.sqlite3" \
     'SELECT run_id, cost_micros, model, input_tokens, output_tokens FROM cost_events;'
   ```

   `cost_micros` is an integer and matches the `total_cost_usd` of the run's `result` event
   (`SELECT payload FROM run_events WHERE kind = ''result''`) times 1,000,000.

4. Approve the push and check the remote.

   ```sh
   uv run labhq approvals approve 1
   git --git-dir "$LABHQ_DATA_DIR/demo/demo/remote.git" rev-parse labhq/task-1-add-a-hello-file
   ```

   The approval line reads `executed`, and the remote's branch points at the commit printed
   in step 1.

5. Optional: `uv run labhq health --collect` prints this machine's samples and
   `0 open incident(s)`.

If the run fails, keep the output and `SELECT status, exit FROM runs;`, and record the
failure below rather than rerunning until it passes.

## Result

Recorded runs, newest last. A run is recorded whether it passed or not.

| Date | labhq commit | Claude Code | SDK | Billing | Model | Run | Commits ahead | cost_micros | Push after approve | Run by |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-10-03 | `5cbe430` | 2.1.288 | 0.2.163 | subscription | `claude-haiku-4-5-20251001` | succeeded | 1 (`HELLO.md`) | 121386 (`total_cost_usd` 0.1213864) | executed; remote branch at the pinned commit `600adaa` | owner's machine |

## Phase 1 manual checks

Every Phase 1 behaviour that only a real model can prove, and where its result is
recorded. The `v0.1.0-alpha.1` tag waits until each row has a recorded pass.

| Check | Proves | Issue | Result recorded in |
|---|---|---|---|
| [Claude adapter](claude-adapter.md) | The adapter contract against a real login: events, cost, resume, interrupt as `interrupted` | #6 | `claude-adapter.md`, "Recorded results" |
| [Push guard](push-guard.md) | A real agent cannot push from its worktree, hooked or not | #7 | `push-guard.md`, "Result" |
| [`rtk` A/B](rtk-ab.md) | The `rtk` hook lowers a worker run's input tokens in `cost_events` | #9 | `rtk-ab.md`, "Result" |
| Phase 1 demo (this page) | Task → branch with a commit → cost → pending push → push after approval | #13 | This page, "Result" |
