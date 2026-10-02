# 0003. Run any CLI agent in tmux, next to the Agent SDK adapter

## Status

Proposed.

## Date

2026-10-03

## Context

Phase 1 runs agents through the Claude Agent SDK (`labhq.adapters.claude`). The SDK gives
structured events, a terminal result with `total_cost_usd`, in-process hooks, `interrupt()`
and resume. It only runs Claude Code.

The owner wants to run any coding agent the same way: Claude Code, Codex CLI, Gemini CLI
and Aider. These are interactive terminal programs with no common SDK. What they share is
that each one starts from a command, can be resumed by a command, reacts to keys, and
reports its own usage through a command of its own.

Plan §9 says "no dependency on tmux". This ADR changes that for one adapter.

The adapter registry already allows a new adapter without touching the dispatcher, and the
`Adapter` protocol (`start`, `events`, `send`, `interrupt`, `result`, `close`) does not
assume the SDK. `agent_task_sessions` already stores a session id and its `cwd` per agent
and task.

## Options considered

1. Keep the SDK only. Every Phase 1 guarantee holds, but only Claude Code can work.
2. Replace the SDK with tmux. One code path for every agent, but cost becomes a screen
   reading for Claude as well, interrupts lose their `terminal_reason`, and in-process hooks
   go away. Native Windows loses every agent.
3. Add a `tmux` adapter next to the SDK adapter. The SDK path keeps the Phase 1 acceptance
   criteria; the tmux path runs any agent with weaker, documented guarantees.

## Decision

Option 3.

### Agents are data

Each supported agent is one registry entry. Adding an agent never adds a branch:

| Field | Meaning |
|---|---|
| `start` | Command template that starts a fresh session in the task's worktree |
| `resume` | Command template that reopens a stored session id |
| `session_id` | How the id is known: assigned up front by labhq, or discovered after start |
| `interrupt_keys` | Keys sent with `tmux send-keys` to stop the current turn |
| `turn_end` | How the end of a turn is detected: a native signal, or screen quiescence |
| `usage_command` | The agent's own command that prints usage |
| `hooks` | How the push guard is installed, or none |

The exact commands and flags of each agent are verified and recorded when the adapter is
built, with a captured screen per agent as a test fixture. This ADR does not assert them.

### Sessions run on a private tmux server

labhq starts its own tmux server on a dedicated socket (`tmux -L labhq`), one session per
run. A tmux session inherits the environment of the tmux server, not of the client that
created it. A server shared with the user would hand workers the user's `SSH_AUTH_SOCK`,
forge tokens and credential helpers. The private server starts from the same allowlisted
environment as the SDK adapter, and `worker_environment` applies on top (ADR 0001). The
user can still watch or take over a run with `tmux -L labhq attach -t <run>`.

### Resume

A run that ends records its session id in `agent_task_sessions`, as the SDK adapter does.
The next run of the same agent on the same task starts with the agent's `resume` template
in the same `cwd`. Where an agent can take an id at start, labhq assigns it and never has to
discover it.

### Usage is read from the screen by a separate extractor

1. When the agent is idle, labhq sends its `usage_command` and captures the pane with
   `tmux capture-pane`.
2. A separate one-shot extraction call turns the captured text into JSON with a fixed
   schema (`unit`, `value`, optional `limit` and `resets_at`). The extractor is itself a
   registry entry and runs with no tools.
3. The JSON is validated by a Pydantic model, and every number in it must appear verbatim
   in the captured text. A reading that fails either check is recorded as failed, never as
   zero.

The worker never extracts its own usage. It would be reporting the numbers that decide
whether its budget stops it, text in the repository could instruct it to under-report, and
each reading would grow its context.

Readings come in different units: USD for an API key, a percentage of a plan limit for a
subscription, tokens for others. A USD reading becomes a `cost_events` row through
`labhq.money` (ADR 0002). Other units go to a new table of usage readings, keyed by agent,
run, unit and time. How a budget is set and enforced for a non-USD unit is decided in the
issue that builds the adapter, before its code.

### Weaker guarantees, stated

- The push guard's transport layers (disabled push URL, no credentials) apply to every
  agent. The parsed-command hook applies only to agents that can run an external hook
  command; that needs a command-line entry point for `labhq.guards.check_command`.
- A run's status comes from the turn-end signal and the process exit, not from a
  `terminal_reason`. An interrupt sent by labhq is recorded as `interrupted` because labhq
  sent it.
- The tmux adapter does not run on native Windows. There, only the SDK adapter is
  available.

## Consequences

- Plan §9 changes from "no dependency on tmux" to "tmux only for the `tmux` adapter" when
  this ADR is accepted.
- The Phase 1 acceptance criteria stay on the SDK adapter. The tmux adapter lands after the
  CLI and demo issue (#13), as its own issue.
- CI installs tmux. Tests run a fake agent script inside a real private tmux server and use
  a fake extractor; no test calls a real model. A missing tmux fails the tests instead of
  skipping them.
- Every usage reading costs one small model call. Its own cost is recorded like any other
  run.
- If an agent changes its screen output, only its fixture and possibly its `turn_end` rule
  change; the extractor absorbs layout changes in the usage output.
