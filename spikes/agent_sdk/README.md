# Claude Agent SDK spike (Phase 0)

Four experiments proving SDK behaviours the orchestrator depends on. See `RESULTS.md`.

Requirements: `uv`, Claude Code on `PATH` and logged in. No `ANTHROPIC_API_KEY`.

```sh
uv sync
uv run python run_all.py                 # all four (about 90 s, a few cents)
uv run python run_all.py interrupt resume  # a subset
uv run ruff check .
```

Experiments live in `spike/`, one module each. They run in throwaway temp dirs
and use `claude-haiku-4-5-20251001`. Exit code is non-zero if any experiment fails.
