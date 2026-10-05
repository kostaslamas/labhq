# 0003. Run any CLI agent in tmux, next to the Agent SDK adapter

## Status

Accepted (2026-10-03). Amended (2026-10-03) after review: the tmux environment, usage from
the Claude Code statusline, and labhq's share of a plan limit.

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
| `usage_source` | Where usage is read: a structured source the CLI provides (for Claude Code, the statusline JSON), or the screen through the extractor |
| `usage_command` | The agent's own command that prints usage, for agents whose `usage_source` is the screen |
| `hooks` | How the push guard is installed, or none |

The exact commands and flags of each agent are verified and recorded when the adapter is
built, with a captured screen per agent as a test fixture. This ADR does not assert them.

### Sessions run on a private tmux server

labhq starts its own tmux server on a dedicated socket (`tmux -L labhq`). Ordinary runs
use one session per run. The global CEO keeps one named session per CLI kind, such as
`ceo_claude` or `ceo_codex`, across owner messages and project wakeups. A server shared
with the user would hand workers the user's `SSH_AUTH_SOCK`, forge
tokens and credential helpers.

A private server alone does not keep them out. A new session starts from the server's
global environment, and the server takes that environment from the client that started
it. On top of that, tmux's `update-environment` option copies a list of variables from the
client that runs `new-session` into the new session; by default the list includes
`SSH_AUTH_SOCK`, `SSH_AGENT_PID`, `SSH_CONNECTION`, `SSH_ASKPASS`, `KRB5CCNAME`, `DISPLAY`
and `XAUTHORITY` (checked on tmux 3.4). So:

1. labhq invokes every tmux command with the allowlisted environment of the SDK adapter
   (ADR 0001), never with its own process environment, so the server it starts holds only
   that.
2. The private server sets `update-environment` to empty before any session is created,
   from a labhq-owned configuration file given with `-f`, so the user's `~/.tmux.conf`
   cannot add variables back.
3. Each session receives its variables explicitly: the allowlist with `worker_environment`
   on top, passed as `new-session -e NAME=value`.

The user can still watch or take over a run with `tmux -L labhq attach -t <run>`.
For the CEO, attach to `ceo_claude` or `ceo_codex`. labhq reuses a live managed CEO pane;
if its CLI exited, labhq respawns it in the same tmux session and resumes its recorded
conversation when the CLI supports resume. A preexisting pane without labhq's ownership
marker is left untouched.

### Resume

A run that ends records its session id in `agent_task_sessions`, as the SDK adapter does.
The next run of the same agent on the same task starts with the agent's `resume` template
in the same `cwd`. Where an agent can take an id at start, labhq assigns it and never has to
discover it.

The global CEO resumes the most recent conversation of each CLI kind from its run records,
including direct owner messages without a task. Its working directory and operational skill
live in the CEO agent home. Its MCP tool server binds each call to the CEO's current run,
so a persistent CLI does not keep a stale run ID.

### Usage comes from a structured source where the CLI has one

Each registry entry names its `usage_source`.

For Claude Code it is the statusline. Claude Code runs the configured statusline command
with a JSON document on stdin, which ADR 0001 names as an official source of limits and
usage. labhq gives the sessions it starts its own statusline command, through settings
passed at start and never by editing the owner's settings files (the exact flag is verified
when this is built). The command writes the JSON to a per-run file the engine reads. No
model is called. Fields, from the Claude Code statusline documentation
(https://code.claude.com/docs/en/statusline, checked 2026-10-03):

- `rate_limits.five_hour.used_percentage` and `rate_limits.seven_day.used_percentage`:
  percentage of the five-hour and seven-day windows used, 0 to 100.
- `rate_limits.five_hour.resets_at` and `rate_limits.seven_day.resets_at`: Unix epoch
  seconds when each window resets.
- `cost.total_cost_usd`: the session's estimated cost in USD, computed client-side.

`rate_limits` is present only for Pro and Max subscribers, and only after the session's
first API response; each window may be absent on its own. An absent window is recorded as
no reading, never as zero. The command runs again after each assistant message and when a
window's `resets_at` passes, so the reading is as fresh as the last turn.

### Otherwise usage is read from the screen by a separate extractor

For CLIs without a structured source:

1. When the agent is idle, labhq sends its `usage_command` and captures the pane with
   `tmux capture-pane`.
2. A separate one-shot extraction call turns the captured text into JSON with a fixed
   schema (`unit`, `value`, optional `window`, `limit` and `resets_at`). The extractor is itself a
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
run, unit, window and time.

### labhq uses a capped share of each plan window

On a subscription the plan's own limit is shared by labhq's agents and the owner's own
use. labhq caps its agents so that part of every window stays for the owner (owner
decision, 2026-10-03):

1. For each plan window the readings report (for Claude Code, the five-hour and the weekly
   window), labhq warns the owner when the latest reading reaches 50%, and starts no new
   run for that agent kind from 70% until that window's `resets_at`. That leaves 30% for the
   owner's own use. Both thresholds are settings (`plan_usage_warn_percent`, default 50;
   `plan_usage_stop_percent`, default 70), not constants.
2. The readings measure the whole account, the owner's own sessions included, so the cap
   holds the account's total, not only labhq's part.
3. The check runs where the budget checks run (plan §7, rule 3): when work is enqueued and
   again before a run starts. Running turns are not cut; a turn that started below the
   threshold finishes.
4. A failed or absent reading is never zero. The latest valid reading of a window stands
   until its `resets_at`.
5. The scheduler wakes the paused work after the reset time.

The cap can still be overrun, by the owner's own use or by a turn that runs past it. The
CLIs print a notice on screen when the plan's limit is reached. The model is not running at
that point, so the engine reads the notice, not the agent:

1. When a turn ends or stalls, the engine captures the pane and the extractor reports
   whether a limit notice is shown, and its reset time.
2. While the limit holds, no new run starts for that agent kind. The owner is notified. The
   scheduler wakes the paused work after the reset time.

In both cases, if the agent's configuration names a fallback agent kind, the task continues
there. Sessions do not move between CLIs, so the fallback starts from the status file and
the commits, not from the conversation.

This carries out ADR 0001's consequences on limits: the per-run budget and turn limit keep
one run from exhausting the plan unnoticed, the cap keeps all of labhq's runs together from
doing so, and both keep scheduled agents closer to the "ordinary, individual usage" that
ADR 0001's low default concurrency aims at.

USD budgets stay as they are (plan §7) for runs billed to an API key.

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
- A test sets a variable (for example `SSH_AUTH_SOCK`) only in the environment of the client
  that runs `tmux`, and asserts that the variable is absent inside the session.
- A Claude Code usage reading comes from the statusline JSON and costs no model call. A test
  feeds a captured statusline document, with and without `rate_limits`, and checks the
  recorded readings. A screen reading costs one small model call, recorded like any other
  run.
- Tests with the fake clock check both thresholds: a warning at the warning percentage, no
  new run at the stop percentage, a running turn left alone, and work resumed after the
  window's `resets_at`.
- If an agent changes its screen output, only its fixture and possibly its `turn_end` rule
  change; the extractor absorbs layout changes in the usage output.
