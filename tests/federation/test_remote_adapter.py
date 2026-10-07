"""The `remote` adapter: its edge cases. The shared contract runs in tests/adapters."""

from pathlib import Path

import pytest

from labhq.adapters import RunRequest, default_registry
from labhq.adapters.base import AdapterError
from labhq.adapters.contract import run_once
from labhq.adapters.remote import RemoteAdapter
from labhq.db.enums import RunStatus
from labhq.db.models import FederationOrder, Run
from labhq.runs.status import status_for
from tests.federation.conftest import Pairing
from tests.federation.harness import RecordingQueue


async def test_an_interrupt_before_the_order_is_queued_sends_nothing(tmp_path: Path) -> None:
    queue = RecordingQueue()
    adapter = RemoteAdapter(queue)

    async def interrupt_first(adapter: RemoteAdapter, event: object) -> None:
        await adapter.interrupt()

    _, result = await run_once(
        adapter,
        RunRequest(prompt="x", cwd=tmp_path, run_id=3),
        interrupt_first,  # type: ignore[arg-type]
    )

    assert queue.queued == []
    assert status_for(result) is RunStatus.INTERRUPTED


async def test_a_run_without_an_id_cannot_start() -> None:
    with pytest.raises(AdapterError, match="run id"):
        await RemoteAdapter(RecordingQueue()).start(RunRequest(prompt="x"))


async def test_a_failed_queue_fails_the_run_with_the_reason(tmp_path: Path) -> None:
    class Broken:
        async def queue(self, run_id: int) -> str:
            raise RuntimeError("node is revoked")

    with pytest.raises(AdapterError, match="node is revoked"):
        await run_once(RemoteAdapter(Broken()), RunRequest(prompt="x", cwd=tmp_path, run_id=1))


def test_the_remote_adapter_is_registered_like_any_other() -> None:
    assert "remote" in default_registry.adapter_keys()
    assert isinstance(default_registry.create("remote"), RemoteAdapter)


async def test_a_manager_run_on_a_revoked_node_fails_and_queues_nothing(
    pairing: Pairing,
) -> None:
    from labhq.federation.nodes import Nodes

    a = pairing.upstream
    await Nodes(a.sessions, clock=a.clock).revoke("lab-b")

    await a.call("delegate_task", a.ceo, project="lab", title="To a revoked node")
    await a.drain()

    assert await a.all(FederationOrder) == []
    [run] = await a.all(Run)
    assert run.status is RunStatus.FAILED
