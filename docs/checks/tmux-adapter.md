# Manual check: four CLI agents through the tmux adapter

CI runs the tmux adapter against a fake agent script inside a real private tmux server
(`tests/adapters/tmux/`), and the usage extractor against captured screens with a fake
extractor (`tests/usage/`). Only the real CLIs can prove that their commands, flags, turn
signals and usage screens still match the registry in `labhq.adapters.tmux.agents`, so this
is a manual check, run on a developer machine. Tests never do this (CONTRIBUTING.md §7).

## What it proves

For each of Claude Code, Codex CLI, Gemini CLI and Aider:

| Step | Passes when |
|---|---|
| One task | A run on the agent kind ends `succeeded`, and the task branch has the agent's commit |
| Resume | A second run on the same task starts with the kind's `resume` template, in the same worktree, and the agent remembers the first turn |
| Usage | One usage reading is recorded: `usage_readings` rows with a value, or a `cost_events` row from a USD reading. For Claude Code it comes from the statusline, with no extraction run |
| Push guard | Asked to `git push`, the agent fails: the hook of Claude Code or Codex CLI denies it; the others fail at the disabled push URL |

## Weaker guarantees (ADR 0003)

- Claude Code and Codex CLI install the push guard hook (`PreToolUse`, through
  `python -m labhq.guards.hook_command`; Claude Code in `--settings`, Codex in `-c hooks.*`,
  see docs/checks/codex-adapter.md). Aider runs no external hook command labhq can pass,
  and Gemini CLI reads hooks only from settings files, which labhq does not write. Those
  agents rely on the other two layers: the worktree's push URL points nowhere, and the
  worker environment holds no git credentials.
- A run's status comes from the turn-end signal and the process exit. Claude Code and Codex
  CLI signal through their `Stop` hooks, Aider by exiting after `--message`;
  Gemini CLI's turn ends when its screen is quiet for `quiescence_seconds`.
- The tmux adapter does not run on native Windows.

## Before you run it

- tmux 3.x and the four CLIs are installed and logged in with their own flows. labhq never
  reads or handles their logins (ADR 0001).
- An extractor agent for screen readings: a `claude` agent with `{"tools": [], "max_turns":
  1}` in its config, approved, its id in `LABHQ_USAGE_EXTRACTOR_AGENT_ID`. Its runs are
  ordinary runs; their cost is recorded like any other.
- Each check costs a few cents per agent, plus one extraction run per screen reading.

## Run it

Resume, per agent kind, through the adapter contract (a temporary directory, two runs, the
second resumes the first session; `interrupt` is left out for kinds without a
`reply_pattern`, because their screens show no assistant messages to interrupt on. Codex has
one; its full contract run is in docs/checks/codex-adapter.md):

```sh
uv sync
for kind in claude-code codex gemini aider; do
  uv run python -m labhq.adapters.contract tmux --config "{\"agent\": \"$kind\"}" \
    --check completes --check resume
done
```

One task with a usage reading, per agent kind, through the engine:

```sh
uv run labhq init
uv run labhq project add --name tmux-check --repo /path/to/a/scratch/repo
uv run labhq agent add --project tmux-check --role worker --title Extractor \
  --adapter claude --config '{"tools": [], "max_turns": 1}'
export LABHQ_USAGE_EXTRACTOR_AGENT_ID=<its id>
uv run labhq agent add --project tmux-check --role worker --title codex \
  --adapter tmux --config '{"agent": "codex"}'
uv run labhq agent approve <each id>
uv run labhq task add --project tmux-check --title "Add a CHANGELOG line" --assignee <agent id>
uv run labhq run
sqlite3 "$LABHQ_DATA_DIR/labhq.sqlite3" \
  'select agent_kind, source, unit, "window", value, error from usage_readings order by id desc limit 5'
```

Watch a run live with `tmux -L labhq attach -t run-<run id>` (detach with `C-b d`).

When a CLI's screen changes, replace its fixture under `tests/usage/fixtures/` with a fresh
capture (`tmux -L labhq capture-pane -p -J -S - -t run-<id>`) and adjust the entry's
`turn_end` if needed.

## Recorded results

Record every run here: date, each CLI's version, billing path, the result per step, the
extraction cost, and who ran it.

| Date | Agent | Version | One task | Resume | Usage reading | Push guard | Run by |
|---|---|---|---|---|---|---|---|
| | claude-code | | not run yet | | | | |
| | codex | | not run yet | | | | |
| | gemini | | not run yet | | | | |
| | aider | | not run yet | | | | |
