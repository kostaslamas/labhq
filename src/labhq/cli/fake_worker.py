"""The CLI's `fake` adapter: the scripted fake, plus the one thing a worker must leave behind.

`labhq.adapters.FakeAdapter` never touches files, so a run on it would leave the task
branch empty and the demo would have nothing to publish. This fake commits one line in the
run's working directory before it reports its result, the way a real worker commits its
work. It commits with the worker environment, so it has no more access than a real agent.
"""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from labhq.adapters import AdapterError, AdapterEvent, FakeAdapter, RunRequest
from labhq.worktrees import worker_environment
from labhq.worktrees.git import run_git

WORK_FILE = "LABHQ_FAKE_WORK.md"
COMMIT_MESSAGE = "docs: record a fake worker run"
# The fake signs its own commits, so the demo needs no git identity on the machine.
IDENTITY = ("-c", "user.name=labhq fake worker", "-c", "user.email=fake-worker@labhq.invalid")


def commit_work(cwd: Path, prompt: str) -> str:
    """Append the brief to the work file, commit it and return the new commit."""
    path = cwd / WORK_FILE
    first_line = prompt.strip().splitlines()[0] if prompt.strip() else "(empty brief)"
    with path.open("a", encoding="utf-8") as work:
        work.write(f"- {first_line}\n")
    environment = worker_environment()
    run_git("add", WORK_FILE, cwd=cwd, env=environment)
    run_git(*IDENTITY, "commit", "--quiet", "-m", COMMIT_MESSAGE, cwd=cwd, env=environment)
    return run_git("rev-parse", "HEAD", cwd=cwd, env=environment).strip()


class CommittingFakeAdapter(FakeAdapter):
    async def start(self, request: RunRequest) -> None:
        if request.cwd is None:
            raise AdapterError("the fake worker needs a working directory to commit in")
        self._brief = request
        await super().start(request)

    async def events(self) -> AsyncIterator[AdapterEvent]:
        async for event in super().events():
            if event.kind == "result":
                commit = await asyncio.to_thread(commit_work, self._cwd(), self._brief.prompt)
                yield AdapterEvent("commit", {"commit": commit, "file": WORK_FILE})
            yield event

    def _cwd(self) -> Path:
        assert self._brief.cwd is not None
        return self._brief.cwd
