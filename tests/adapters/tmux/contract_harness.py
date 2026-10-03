"""The tmux adapter under the shared adapter contract, running the fake agent.

The contract's prompts are written for a model; the harness maps each to the fake agent's
words, and reports the screen line where the fake waits as the assistant event the
interrupt check waits for.
"""

import contextlib
import uuid
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path

from labhq.adapters import AdapterEvent, AdapterFactory, RunRequest
from labhq.adapters.contract import INTERRUPT_PROMPT
from labhq.adapters.tmux import TmuxAdapter, TmuxServer
from labhq.clock import SystemClock
from tests.adapters.tmux.conftest import agent_config, fake_kinds, require_tmux


class ContractTmuxAdapter(TmuxAdapter):
    async def start(self, request: RunRequest) -> None:
        prompt = "WAIT" if request.prompt == INTERRUPT_PROMPT else "contract"
        await super().start(replace(request, prompt=prompt, config=agent_config()))

    async def events(self) -> AsyncIterator[AdapterEvent]:
        async for event in super().events():
            if "waiting" in event.payload.get("lines", []):
                yield AdapterEvent("assistant", event.payload)
                continue
            yield event


def tmux_harness(check: str, tmp_path: Path, stack: contextlib.ExitStack) -> AdapterFactory:
    require_tmux()
    server = TmuxServer(socket=f"labhq-test-{uuid.uuid4().hex[:12]}", state_dir=tmp_path / "tmux")
    stack.callback(server.kill_server)
    kinds = fake_kinds()
    return lambda: ContractTmuxAdapter(server=server, kinds=kinds, clock=SystemClock())
