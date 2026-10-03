# Manual check: graphify index A/B

Plan §7.1 keeps a token-economy measure only if it is measured. This check proves that a
project's manager answers a structural question from the graphify index
(`labhq.economy.graphify`) instead of reading files, and that this lowers its input tokens
without losing quality. It needs a real model, so it is not a test: the owner runs it on a
developer machine and records the result below.

## What is compared

The same question, asked twice of the same manager on the same commit:

- **A**: without the index (`agents.config["graphify"]` is `false` or absent; the system
  prompt has no "Code graph" section).
- **B**: with the index (`agents.config["graphify"] = true`, `graphify` on `PATH` and the
  project's index built; the system prompt has the "Code graph" section).

The measure is input tokens as recorded by the engine: `cost_events.input_tokens` plus
`cost_events.cache_read_input_tokens` and `cost_events.cache_creation_input_tokens`, summed
per run, cross-checked against `runs.usage`. Cost in micros is reported too. Quality is the
owner's note on whether B's answer is as correct and as complete as A's.

## Prerequisites

- A working labhq install with the run engine and the CLI.
- Claude Code installed and logged in, or `ANTHROPIC_API_KEY` set (ADR 0001). `cli_path`
  pins the installed Claude Code binary.
- graphify installed: `uv tool install graphifyy` (or `pipx install graphifyy`). Record
  `uv tool list | grep graphifyy` (the module was written against 0.9.74). Do not run
  `graphify install` or `graphify claude install`: they edit `CLAUDE.md` and Claude Code's
  hooks, which would leak the index into run A.
- A real project of a few hundred source files that the owner knows well enough to judge an
  answer about its structure.

## Procedure

1. Point labhq at a scratch data directory so the runs are the only rows:
   `export LABHQ_DATA_DIR=/tmp/labhq-graphify-ab`, then `uv run labhq init`.
2. Add the project and one manager on a cheap model with a fixed `max_turns`, and give the
   manager a role that may read the repository (Bash, Read, Grep).
3. Build the index: start the always-on program (`uv run labhq serve`) and wait for the
   `graphify` loop's first pass, or call `GraphifyIndex.build` once. Check that
   `$LABHQ_DATA_DIR/graphify/<project_id>/graphify-out/graph.json` exists and that
   `git status --porcelain --ignored` in the project is unchanged by the build.
4. Use one structural question verbatim for both runs, chosen so the answer spans several
   files, for example:
   > Which functions call into the database layer when a request is authenticated, and in
   > which files do they live? List them; do not change any file.
5. **Run A.** With `"graphify": false` on the manager, ask the question and wait for the run
   to end. Confirm the run's system prompt has no "Code graph" section and that its events
   show file reads (Read, Grep, `cat`).
6. **Run B.** Set `"graphify": true` on the manager, ask the same question, and wait. Confirm
   the events show `graphify query`, `explain` or `path` calls before any file read.
7. Compare. With `sqlite3 $LABHQ_DATA_DIR/labhq.sqlite3`:

   ```sql
   SELECT r.id,
          r.status,
          json_extract(a.config, '$.graphify') AS graphify,
          SUM(c.input_tokens) AS input_tokens,
          SUM(c.cache_read_input_tokens) AS cache_read,
          SUM(c.cache_creation_input_tokens) AS cache_creation,
          SUM(c.input_tokens + c.cache_read_input_tokens + c.cache_creation_input_tokens)
              AS total_input,
          SUM(c.cost_micros) AS cost_micros
   FROM runs AS r
   JOIN agents AS a ON a.id = r.agent_id
   JOIN cost_events AS c ON c.run_id = r.id
   GROUP BY r.id
   ORDER BY r.id;
   ```

   `graphify` shows the switch as it is now, not as it was for the run: note which run id
   was A and which was B as you go.
8. Repeat steps 5 to 7 two more times, alternating which run goes first (A-B, B-A, A-B), so a
   cache warmed by the first run does not favour the second. Use a fresh session each time
   (no resume), so B does not inherit A's file reads.
9. Judge quality: B's answer names the same functions and files as A's, or better ones. A
   drop in tokens with a worse answer is a failure, not a saving.

## Pass condition

In every pair, B's `total_input` is lower than A's, both runs succeed, and B's answer is at
least as good as A's. Report the median drop as a percentage of A. If it passes, managers get
`"graphify": true` by default; if not, the switch stays off and the result is recorded here.

## Result

Not run yet. The owner records each pair here, newest last:

| Date | labhq commit | Claude Code | graphify | Model | Pair | A total_input | B total_input | Drop | Quality note |
|---|---|---|---|---|---|---|---|---|---|
