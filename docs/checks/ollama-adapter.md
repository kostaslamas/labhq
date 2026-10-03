# Manual check: the Ollama adapter against a real local Ollama

CI proves the adapter contract for `ollama` against a fake `/api/chat` built on
`httpx.MockTransport` (`tests/adapters/test_contract.py`, `tests/adapters/test_ollama*.py`).
Only a running Ollama with a model pulled can prove the same contract end to end, so it is a
manual check, run on a developer machine. Tests never do this (CONTRIBUTING.md §7).

## What it proves

The same checks as CI, from `labhq.adapters.contract`, on the adapter the default registry
builds for `ollama`:

| Check | Prompt | Passes when |
|---|---|---|
| `completes` | Reply with the single word OK. | Chunks stream as `assistant` events, the last event is the result, it maps to `succeeded`, a session id is reported, cost is `$0.0000` |
| `interrupt` | Run `sleep 30` with the Bash tool, then reply DONE. | `interrupt()` on the first streamed chunk closes the request and the result maps to `interrupted` (`terminal_reason` `aborted_streaming`). The model has no tools; it only has to start answering |
| `resume` | Remember the codeword AURORA-7 ..., then What was the codeword? | The second run, started with the first run's session id, sends the stored conversation, succeeds and keeps the session id |

`completes` and `resume` print `$0.0000`: a local model costs nothing per token, and runs
record a `cost_events` row of 0 micros (ADR 0002).

## Before you run it

- Ollama is installed and serving: `ollama serve` (or the desktop app) is running and
  `curl http://127.0.0.1:11434/api/version` answers. labhq neither installs Ollama nor
  pulls models.
- A small model is pulled, for example `ollama pull llama3.2:1b`.
- Point the adapter at it. Defaults come from `LABHQ_OLLAMA_*` settings and an agent's
  `config` (`base_url`, `model`, `system`, `options`) overrides them:
  - `LABHQ_OLLAMA_BASE_URL`, default `http://127.0.0.1:11434`
  - `LABHQ_OLLAMA_MODEL`, default `llama3.2`
- The conversation of each session is stored under `<data dir>/ollama-sessions/`. Set
  `LABHQ_DATA_DIR` to a scratch directory to keep the check's sessions out of your own.

## Run it

```sh
uv sync
LABHQ_OLLAMA_MODEL=llama3.2:1b LABHQ_DATA_DIR="$(mktemp -d)" \
  uv run python -m labhq.adapters.contract ollama
```

Each check prints `PASS` or `FAIL` with its cost, then the total. The exit status is 0 only
when every check passed.

To see the failure messages, stop Ollama and run it again: every check fails with
`cannot reach Ollama at http://127.0.0.1:11434: start it with ollama serve ...`. With a model
that is not pulled (`LABHQ_OLLAMA_MODEL=nope:1b`) the message says `pull it with ollama pull
nope:1b`.

## Recorded results

Record every run here: date, `ollama --version`, model, the output, and who ran it.

| Date | Ollama | Model | Result | Total cost | Run by |
|---|---|---|---|---|---|
| | | | Not run yet: waiting for the owner to run it against a real local Ollama | | |
