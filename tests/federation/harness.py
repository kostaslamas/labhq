"""A `remote` adapter for the adapter contract: contract requests carry no run id, real ones do."""

import contextlib
from pathlib import Path

from labhq.adapters import AdapterFactory, RunRequest
from labhq.adapters.remote import RemoteAdapter

RUN_ID = 7


class RecordingQueue:
    def __init__(self) -> None:
        self.queued: list[int] = []

    async def queue(self, run_id: int) -> str:
        self.queued.append(run_id)
        return f"queued {run_id}"


class IdentifiedRemoteAdapter(RemoteAdapter):
    async def start(self, request: RunRequest) -> None:
        await super().start(
            RunRequest(
                prompt=request.prompt,
                cwd=request.cwd,
                resume_session_id=request.resume_session_id,
                config=request.config,
                run_id=RUN_ID,
            )
        )


def remote_harness(check: str, tmp_path: Path, stack: contextlib.ExitStack) -> AdapterFactory:
    queue = RecordingQueue()
    return lambda: IdentifiedRemoteAdapter(queue)
