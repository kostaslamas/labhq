# labhq: notes for agent contributors

labhq is an open-source, self-hosted project orchestrator for one person with many
projects and a team of AI agents. Phase 1 builds the engine: data model, runs, adapters,
worktrees, scheduler, budgets, approvals, health rules and the CLI.

Read these before changing anything:

- @CONTRIBUTING.md: the conventions. They are binding.
- `planning/plan.md`: design and acceptance criteria, in Greek. §6 is the data model, §7 the
  scheduler, §5 approvals and security, §10 the phases.
- `docs/adr/`: accepted decisions. ADR 0001 (billing, credentials) and ADR 0002 (cost in
  integer micro-USD) constrain Phase 1 directly.
- `spikes/agent_sdk/RESULTS.md`: measured Agent SDK behaviour (hooks under
  `bypassPermissions`, interrupt, resume, `can_use_tool`). Trust it over memory.

## Working on an issue

1. Read the issue and the plan sections it cites. The issue's acceptance criteria are the
   definition of done.
2. Branch from `main` as `type/short-slug`, for example `feat/scheduler`.
3. Stay inside the paths the issue owns (see the map below). If you need a change elsewhere,
   keep it minimal and say why in the pull request.
4. Commit in Conventional Commits, one logical change per commit, with `Refs #N` in the body.
5. Before pushing, run the checks below. All of them must pass.
6. Open a pull request with `gh pr create`. The body says `Closes #N` and lists every
   acceptance criterion next to the test or guard that proves it. A criterion you could not
   prove is listed as not done, with the reason.
7. When every CI check is green, merge it with `gh pr merge --merge --delete-branch`. If CI
   fails, fix and push until it is green. If you are blocked on something only the owner
   can provide, add the label `needs-owner` to the issue, comment why, and stop.

Never push to `main`, create a tag or edit another issue's paths beyond the minimum.

## Checks

```sh
uv sync
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
uv run python -m tools.file_size
uv run alembic upgrade head && uv run alembic check
```

CI runs the same set, plus guards for secrets and private terms. The private-terms list is a
repository secret; you cannot see it, and you do not need to.

## Rules that are easy to miss

- Tests never call a real model or need a Claude login. Use the fake adapter. Anything that
  needs a real model is a manual check under `docs/checks/`.
- Never read, copy, store or log Claude credentials or tokens, and never reference credential
  file paths (ADR 0001). The only credential variable passed to a child process is
  `ANTHROPIC_API_KEY`, and only when the user set it.
- Amounts are integer micro-USD in `*_micros` columns. Convert SDK floats only through
  `labhq.money` (ADR 0002).
- Time comes from the injectable clock in `labhq.clock`. Instants are UTC and timezone-aware.
- Schema changes are Alembic migrations, never `create_all`. Keep a single Alembic head:
  rebase onto `main` and re-parent your migration if another one landed first.
- An interrupted run ends as `interrupted`, not `failed` (`terminal_reason` is
  `aborted_streaming`, see the spike results).
- Pin the Claude Code binary through `cli_path`; the SDK wheel bundles a different version.
- Foundation declares every Phase 1 dependency. If you must add one, use `uv add`, and on a
  `uv.lock` conflict rebase and re-run `uv lock` instead of merging the lock file by hand.

## Module ownership in Phase 1

| Path | Owner issue |
|---|---|
| `pyproject.toml`, `uv.lock`, `src/labhq/settings.py`, `clock.py`, `money.py`, `src/labhq/db/`, `migrations/`, `tools/file_size.py`, `.github/workflows/ci.yml`, `.claude/settings.json` | Foundation |
| `tools/guards/`, `.github/workflows/guards.yml` | CI guards |
| `src/labhq/adapters/`, `src/labhq/runs/` | Adapters and runs |
| `src/labhq/worktrees/`, `src/labhq/guards/` | Worktrees and push guard |
| `src/labhq/health/` | Health collector and rules |
| `src/labhq/economy/` | Token economy (output style, handoffs, `rtk`) |
| `src/labhq/budgets/` | Budgets |
| `src/labhq/scheduler/` | Scheduler |
| `src/labhq/approvals/` | Approvals |
| `src/labhq/cli/`, `docs/checks/` | CLI and demo |

Tests mirror the source tree under `tests/`.

## Module ownership in Phase 2

| Path | Owner issue |
|---|---|
| `pyproject.toml`, `uv.lock`, `migrations/versions/0003_*`, `src/labhq/db/models/callcenter.py`, `src/labhq/db/enums.py` (Phase 2 values), `src/labhq/speech/`, `src/labhq/work/`, `src/labhq/callcenter/settings.py` | #31 Phase 2 foundation |
| `src/labhq/notify/`, `src/labhq/cli/notify.py`, `docs/checks/notifier.md` | #32 Notifier |
| `src/labhq/mcp/server.py`, `src/labhq/mcp/auth.py`, `src/labhq/mcp/tools/registry.py`, `src/labhq/cli/mcp.py` | #33 MCP server |
| `src/labhq/callcenter/answers/` | #34 Program answers |
| `src/labhq/callcenter/actions/` | #35 Decide and order |
| `src/labhq/callcenter/status/`, `src/labhq/callcenter/questions/`, `src/labhq/callcenter/deliveries/` | #36 Agent questions |
| `src/labhq/expose/`, `docs/checks/connector.md` | #37 Exposure |
| `src/labhq/mcp/tools/` (except `registry.py`), the inspector step in `.github/workflows/ci.yml` | #38 Call Center tools |
| `src/labhq/callcenter/calls/`, `docs/checks/voice.md` | #39 ask_ceo and get_reply |

New CLI commands register in `src/labhq/cli/__init__.py` with a one-line edit each.
