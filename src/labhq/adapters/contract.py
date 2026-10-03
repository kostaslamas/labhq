"""The behaviour every adapter must show, as checks that run against any adapter factory.

CI runs these against the fake and against the Claude adapter with its SDK client stubbed.
`python -m labhq.adapters.contract claude` runs them against a real login; see
docs/checks/claude-adapter.md. `... contract ollama` runs them against a local Ollama; see
docs/checks/ollama-adapter.md. The prompts are chosen so a real model can satisfy them.
"""

import argparse
import asyncio
import sys
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path

from labhq.adapters.base import Adapter, AdapterEvent, AdapterResult, RunRequest
from labhq.adapters.registry import AdapterFactory
from labhq.db.enums import RunStatus
from labhq.money import format_micros, usd_to_micros
from labhq.runs.status import status_for

COMPLETE_PROMPT = "Reply with the single word OK."
INTERRUPT_PROMPT = "Run `sleep 30` with the Bash tool, then reply with the single word DONE."
REMEMBER_PROMPT = "Remember the codeword AURORA-7 and reply with the single word OK."
RECALL_PROMPT = "What was the codeword?"
# A real model needs a few turns for a tool call; the scripted adapters ignore it.
CONTRACT_CONFIG = {"max_turns": 4}


class ContractViolationError(AssertionError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractViolationError(message)


async def run_once(
    adapter: Adapter,
    request: RunRequest,
    on_event: Callable[[Adapter, AdapterEvent], Awaitable[None]] | None = None,
) -> tuple[list[AdapterEvent], AdapterResult]:
    events: list[AdapterEvent] = []
    await adapter.start(request)
    try:
        async for event in adapter.events():
            events.append(event)
            if on_event is not None:
                await on_event(adapter, event)
        return events, adapter.result()
    finally:
        await adapter.close()


def _request(prompt: str, cwd: Path, resume: str | None = None) -> RunRequest:
    return RunRequest(prompt=prompt, cwd=cwd, resume_session_id=resume, config=CONTRACT_CONFIG)


async def check_completes(make: AdapterFactory, cwd: Path) -> list[AdapterResult]:
    events, result = await run_once(make(), _request(COMPLETE_PROMPT, cwd))
    require(bool(events), "a run streams at least one event")
    require(events[-1].kind == "result", "the last event is the result")
    require(status_for(result) is RunStatus.SUCCEEDED, f"run did not succeed: {result}")
    require(bool(result.session_id), "a finished run reports its session id")
    require(result.cost_usd is None or result.cost_usd >= 0, "cost is never negative")
    return [result]


async def check_interrupt(make: AdapterFactory, cwd: Path) -> list[AdapterResult]:
    sent = False

    async def interrupt_on_assistant(adapter: Adapter, event: AdapterEvent) -> None:
        nonlocal sent
        if event.kind == "assistant" and not sent:
            sent = True
            await adapter.interrupt()

    _, result = await run_once(make(), _request(INTERRUPT_PROMPT, cwd), interrupt_on_assistant)
    require(sent, "the run produced an assistant event to interrupt on")
    require(
        status_for(result) is RunStatus.INTERRUPTED,
        f"an interrupted run must map to interrupted: {result}",
    )
    return [result]


async def check_resume(make: AdapterFactory, cwd: Path) -> list[AdapterResult]:
    _, first = await run_once(make(), _request(REMEMBER_PROMPT, cwd))
    require(bool(first.session_id), "the first run reports a session id")
    _, second = await run_once(make(), _request(RECALL_PROMPT, cwd, resume=first.session_id))
    require(status_for(second) is RunStatus.SUCCEEDED, f"resumed run failed: {second}")
    require(second.session_id == first.session_id, "a resumed run keeps the session id")
    return [first, second]


CHECKS: dict[str, Callable[[AdapterFactory, Path], Awaitable[list[AdapterResult]]]] = {
    "completes": check_completes,
    "interrupt": check_interrupt,
    "resume": check_resume,
}


async def _run_all(key: str, cwd: Path) -> bool:
    from labhq.adapters import default_registry

    def make() -> Adapter:
        return default_registry.create(key)

    passed = True
    total_micros = 0
    for name, check in CHECKS.items():
        try:
            results = await check(make, cwd)
        except Exception as error:  # report every check, not only the first failure
            passed = False
            print(f"FAIL {name}: {error}")
            continue
        micros = sum(usd_to_micros(r.cost_usd or 0) for r in results)
        total_micros += micros
        print(f"PASS {name} ({format_micros(micros)})")
    print(f"total cost {format_micros(total_micros)}")
    return passed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the adapter contract for real.")
    parser.add_argument("adapter", help="registered adapter key, e.g. claude or ollama")
    args = parser.parse_args(argv)
    # Sessions are stored per working directory, so every check shares one.
    with tempfile.TemporaryDirectory(prefix="labhq-contract-") as scratch:
        return 0 if asyncio.run(_run_all(args.adapter, Path(scratch))) else 1


if __name__ == "__main__":
    sys.exit(main())
