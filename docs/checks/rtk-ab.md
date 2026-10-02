# Manual check: `rtk` hook A/B

Plan §7.1 keeps a token-economy measure only if it is measured. This check proves that the
`rtk` PreToolUse hook (`labhq.economy.rtk`) lowers the input tokens of a worker run. It needs
a real model, so it is not a test: the owner runs it on a developer machine and records the
result below.

## What is compared

The same task, run twice by the same worker on the same commit:

- **A**: without the hook (`rtk` not on `PATH`; the run records the `rtk_missing` warning).
- **B**: with the hook (`rtk` on `PATH`; the run records no such warning).

The measure is input tokens as recorded by the engine: `cost_events.input_tokens` plus
`cost_events.cache_read_input_tokens` and `cost_events.cache_creation_input_tokens`, summed
per run, cross-checked against `runs.usage`. Cost in micros is reported but not the criterion,
because cache hits shift it independently of the hook.

## Prerequisites

- A working labhq install with the run engine (adapters and runs issue) and the CLI.
- Claude Code installed and logged in, or `ANTHROPIC_API_KEY` set (ADR 0001). `cli_path`
  pins the installed Claude Code binary.
- `rtk` installed, with the `rewrite` subcommand (`rtk rewrite "git status"` prints
  `rtk git status`). Record `rtk --version`.
- A scratch project whose test suite prints a lot: a few hundred passing tests, or a build
  with verbose logs. The bigger the shell output, the clearer the signal.

## Procedure

1. Point labhq at a scratch database so the two runs are the only rows:
   `export LABHQ_DATABASE_URL=sqlite+aiosqlite:////tmp/labhq-rtk-ab.sqlite3`, then
   `uv run alembic upgrade head`.
2. Create the scratch project and one worker on the same model for both runs. Use a cheap
   model (the spike used `claude-haiku-4-5-20251001`) and a fixed `max_turns`.
3. Use this task text verbatim for both runs:
   > Run the full test suite once, then `git log -n 20`. Report how many tests passed and the
   > subject of the oldest of those commits. Do not change any file.
4. **Run A.** In a shell where `command -v rtk` prints nothing (for example,
   `PATH` without the directory holding `rtk`), start the worker on the task and wait for the
   run to finish. Confirm the run has a `warning` event with code `rtk_missing`.
5. Reset the worktree to the same commit (`git status` is clean, `HEAD` unchanged).
6. **Run B.** In a shell where `command -v rtk` prints its path, start the same worker on the
   same task. Confirm there is no `rtk_missing` warning and that the run events show Bash
   commands prefixed with `rtk`.
7. Compare. With `sqlite3 /tmp/labhq-rtk-ab.sqlite3`:

   ```sql
   SELECT r.id,
          r.status,
          SUM(c.input_tokens) AS input_tokens,
          SUM(c.cache_read_input_tokens) AS cache_read,
          SUM(c.cache_creation_input_tokens) AS cache_creation,
          SUM(c.input_tokens + c.cache_read_input_tokens + c.cache_creation_input_tokens)
              AS total_input,
          SUM(c.cost_micros) AS cost_micros
   FROM runs AS r
   JOIN cost_events AS c ON c.run_id = r.id
   GROUP BY r.id
   ORDER BY r.id;
   ```

8. Repeat steps 4 to 7 two more times, alternating which run goes first (A-B, B-A, A-B), so a
   cache warmed by the first run does not favour the second.
9. Check the answers match: both runs must report the same test count and commit subject.
   A drop in tokens with a wrong answer is a failure, not a saving.

## Pass condition

In every pair, B's `total_input` is lower than A's, both runs succeed, and the answers agree.
Report the median drop as a percentage of A.

## Result

Not yet run. The owner fills this in.

| Date | labhq commit | Claude Code | rtk | Model | Pair | A total_input | B total_input | Drop | Answers agree |
|---|---|---|---|---|---|---|---|---|---|
| | | | | | 1 | | | | |
| | | | | | 2 | | | | |
| | | | | | 3 | | | | |

Median drop: . Verdict (keep the hook on by default or not): .
