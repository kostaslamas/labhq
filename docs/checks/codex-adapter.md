# Manual check: the Codex CLI through the tmux adapter

CI runs the `codex` entry of the tmux adapter's agent registry against a fake `codex`
(`tests/adapters/fake_codex.py`) inside a real private tmux server: the adapter contract
(complete, interrupt, resume), resume in the stored `cwd`, the push guard, and usage readings
from the `/status` screens under `tests/adapters/fixtures/codex/`. The fake reproduces the
real CLI's command line, `-c` parsing, hook trust and hook payloads, and its screens come
from the Codex TUI's own snapshot tests. Only the real CLI can prove that they still match,
so this check runs on a developer machine. Tests never do this (CONTRIBUTING.md §7).

## What the entry relies on

Each field of `CODEX` in `src/labhq/adapters/tmux/agents.py` records its source next to it.
Everything was read in openai/codex at main `86a54b05` on 2026-10-03.

| Field | Value | Source |
|---|---|---|
| `start` | `codex --yolo --dangerously-bypass-hook-trust --no-alt-screen -- PROMPT` | `codex-rs/tui/src/cli.rs`, `codex-rs/utils/cli/src/shared_options.rs` |
| `resume` | `codex resume <same flags> -- SESSION_ID PROMPT` | `codex-rs/cli/src/main.rs` (`ResumeCommand`, root `-c` prepended) |
| `session_id` | read from the `Stop` hook payload, key `session_id` | `codex-rs/hooks/schema/generated/stop.command.input.schema.json` |
| `interrupt_keys` | `Escape` | TUI footer "esc to interrupt" (`codex-rs/tui` chatwidget snapshots) |
| `turn_end` | `signal`: a `Stop` command hook runs `python -m labhq.adapters.tmux.signal turn …` | `codex-rs/hooks/src/events/stop.rs` |
| `usage_source` / `usage_command` | `screen` / `/status`, read by the extractor | `codex-rs/tui/src/status` |
| `hooks` | `PreToolUse` command hook, matcher `Bash`, runs `python -m labhq.guards.hook_command` | `codex-rs/core/src/tools/hook_names.rs`, `codex-rs/hooks/src/events/pre_tool_use.rs` |
| `reply_pattern` | `^• ` except the `• Working (…)` status line | `codex-rs/tui` chatwidget snapshots |

The hooks and settings are passed as `-c key=value` session overrides
(`codex-rs/utils/cli/src/config_override.rs`; `hooks.<Event>` from
`codex-rs/config/src/hook_config.rs`). labhq never edits `~/.codex/config.toml`:

- `features.hooks=true`, in case the owner's config turns hooks off.
- `check_for_update_on_startup=false`, so an update prompt cannot block the first turn.
- `tui.resume_cwd="current"`, so a resume never stops on "which directory?"; labhq resumes in
  the stored `cwd` anyway.
- `hooks.Stop` and `hooks.PreToolUse`, as above. Codex skips hooks from session flags unless
  they are trusted, hence `--dangerously-bypass-hook-trust`. That flag also lets hooks that a
  repository declares in its own `.codex/` run without trust. A worker already runs
  repository code (tests, builds) with no sandbox, so this gives a repository nothing new.

The legacy `notify` program was the turn signal before. `codex-rs/hooks/src/legacy_notify.rs`
marks it for removal, and it cannot block a command, so the entry uses hooks instead.

### Push guard

Codex can run an external hook command before a shell call, so the guard's three layers all
apply: the `PreToolUse` hook denies a publishing command (exit code 2, reason on stderr), the
worktree's push URL points nowhere, and the worker environment holds no git credentials.
CI proves the hook denies `git push`, and proves that with the hook swapped for one that
allows everything, the push still fails at the transport.

### Usage

`/status` shows each plan window as "N% left" (5h, weekly or monthly) and has no "used" form.
The extractor copies the number as unit `percent_left`, and `labhq.usage.schema` turns it into
the share used (`100 - N`), so the extractor never does arithmetic. Any number not on the
screen, the share used included, is rejected and recorded as a failed reading, never as zero.
"Limits: data not available yet" gives no reading.

### Credentials

The session gets the allowlisted environment of ADR 0001. `OPENAI_API_KEY` is not passed
through, so Codex runs on its own login (`codex login`) under `HOME`. labhq never reads,
copies or references that login.

## Before you run it

- tmux 3.x and the Codex CLI (`npm i -g @openai/codex` or the release binary), logged in with
  `codex login`. Record `codex --version`.
- Run `codex` once by hand in a scratch directory and quit, so first-run onboarding is done.
- For the usage reading: an extractor agent as in `docs/checks/tmux-adapter.md` ("Before you
  run it"), with its id in `LABHQ_USAGE_EXTRACTOR_AGENT_ID`.
- Cost: the contract is three short turns plus one interrupted turn; the task is one turn
  plus one extraction run.

## Run it

The contract, with the real binary in a temporary directory (two of the runs share a
session; the interrupt check stops a `sleep 30` with Escape):

```sh
uv sync
uv run python -m labhq.adapters.contract tmux:codex
```

It prints `PASS completes`, `PASS interrupt` and `PASS resume`. The cost line reads $0.00
because the tmux adapter reports no cost; usage is read from the screen after the run.

One real task through the engine, in a scratch repository:

```sh
uv run labhq init
uv run labhq project add --name codex-check --repo /path/to/a/scratch/repo
uv run labhq agent add --project codex-check --role worker --title Extractor \
  --adapter claude --config '{"tools": [], "max_turns": 1}'
export LABHQ_USAGE_EXTRACTOR_AGENT_ID=<its id>
uv run labhq agent add --project codex-check --role worker --title codex \
  --adapter tmux --config '{"agent": "codex"}'
uv run labhq agent approve <each id>
uv run labhq task add --project codex-check --title "Add a CHANGELOG line" --assignee <codex agent id>
uv run labhq run
sqlite3 "$LABHQ_DATA_DIR/labhq.sqlite3" \
  'select agent_kind, source, unit, "window", value, error from usage_readings order by id desc limit 5'
```

Watch it with `tmux -L labhq attach -t run-<run id>` (detach with `C-b d`). Then:

1. The run ends `succeeded` and the task branch has Codex's commit.
2. Run the task again: the second run starts with `codex resume … <session id>` in the same
   worktree, and Codex remembers the first turn.
3. Ask Codex, in a third run, to `git push`: the screen shows the `PreToolUse` hook blocking
   it, and the remote is unchanged.
4. `usage_readings` has `percent` rows for the 5h and weekly windows (or a failed row with
   its error, never a zero).

When the CLI's screens change, replace the fixtures under `tests/adapters/fixtures/codex/`
with live captures (`tmux -L labhq capture-pane -p -J -S - -t run-<id>`), keep the fake in
step, and adjust the entry if a field changed.

## Recorded results

Record every run here: date, `codex --version`, billing path (ChatGPT plan or API key), the
result of each step, the extraction cost, and who ran it.

| Date | Codex version | Billing | Contract | One task | Resume | Push guard | Usage reading | Run by |
|---|---|---|---|---|---|---|---|---|
| | | | not run yet | | | | | |
