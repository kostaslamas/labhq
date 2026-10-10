# Manual check: model policy on a real login

Needs a developer machine with Claude Code logged in. Tests never call a real model, so this
is the one place the policy meets the real binary.

1. `uv run labhq` serve, open Models, confirm the defaults: Sonnet 5.5 for roles and project
   analysis, Haiku 5.5 at `medium` for summaries and checks.
2. Start a run with `task_kind="summary"` (for example the session inventory scan). In the
   run list the model reads `claude-haiku-5-5`; the usage report shows it under cost by model.
3. Start a tmux `claude-code` run: the pane's launch line carries `--model` and `--effort`
   (confirm both flags against `claude --help` of the pinned binary).
4. Give an agent `{"max_thinking_tokens": 4000}` in its config and run it on Haiku 5.5. The
   run must succeed: the adapter drops the budget and keeps adaptive thinking.
5. Ask the Call Center "which model do the workers use". It must read the table. Ask it to
   change one: it only names an approval, and nothing changes until you confirm with the
   passkey.

Record the date, binary version and result here after each run.
