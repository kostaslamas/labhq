"""The fake agent in a real private tmux server: one turn, resume, interrupt."""

from collections.abc import AsyncIterator
from pathlib import Path

from labhq.adapters import AdapterEvent
from labhq.adapters.tmux import TmuxAdapter, split_session
from labhq.db.enums import RunStatus
from tests.adapters.tmux.conftest import AdapterMaker, agent_config
from tests.runs.conftest import World
from tests.runs.helpers import events_of, stored_run, task_sessions, use_adapter


def screen_text(events: list[AdapterEvent] | list[object]) -> str:
    lines: list[str] = []
    for event in events:
        payload = getattr(event, "payload", {})
        lines += payload.get("lines", [])
        if "text" in payload:
            lines.append(payload["text"])
    return "\n".join(lines)


async def test_a_turn_runs_and_ends_inside_the_private_server_and_is_recorded(
    tmux_world: World, tmp_path: Path
) -> None:
    run = await tmux_world.service.execute(
        agent_id=tmux_world.agent_id, task_id=tmux_world.task_id, prompt="hello", cwd=tmp_path
    )

    stored = await stored_run(tmux_world, run.id)
    assert stored.status is RunStatus.SUCCEEDED
    assert stored.adapter == "tmux"
    events = await events_of(tmux_world, run.id)
    kinds = [event.kind for event in events]
    assert kinds[0] == "agent"
    assert events[0].payload == {"kind": "fake-agent", "session": f"run-{run.id}"}
    assert "screen" in kinds
    assert kinds[-3:] == ["usage_screen", "screen_final", "result"]
    assert "LABHQ-FAKE-TURN-END" in screen_text(events)
    assert "37% of the 5h limit" in events[-3].payload["text"]
    kind, session = split_session(stored.session_id_after)
    assert kind == "fake-agent"
    assert session and f"session={session} resumed=False cwd={tmp_path}" in screen_text(events)


async def test_a_second_run_resumes_the_stored_session_in_the_same_cwd(
    tmux_world: World, tmp_path: Path
) -> None:
    first = await tmux_world.service.execute(
        agent_id=tmux_world.agent_id, task_id=tmux_world.task_id, prompt="one", cwd=tmp_path
    )
    # No cwd: the run service takes the stored one, as resume needs.
    second = await tmux_world.service.execute(
        agent_id=tmux_world.agent_id, task_id=tmux_world.task_id, prompt="two"
    )

    before = await stored_run(tmux_world, first.id)
    after = await stored_run(tmux_world, second.id)
    assert after.session_id_before == before.session_id_after
    _, session = split_session(before.session_id_after)
    text = screen_text(await events_of(tmux_world, second.id))
    assert f"session={session} resumed=True cwd={tmp_path}" in text
    (row,) = await task_sessions(tmux_world)
    assert (row.session_id, row.cwd) == (before.session_id_after, str(tmp_path))


async def test_a_session_of_another_agent_kind_is_not_resumed(
    tmux_world: World, tmp_path: Path
) -> None:
    await tmux_world.service.execute(
        agent_id=tmux_world.agent_id, task_id=tmux_world.task_id, prompt="one", cwd=tmp_path
    )
    await use_adapter(tmux_world, "tmux", agent_config("fake-agent-nohook"))
    second = await tmux_world.service.execute(
        agent_id=tmux_world.agent_id, task_id=tmux_world.task_id, prompt="two"
    )

    assert "resumed=False" in screen_text(await events_of(tmux_world, second.id))


class InterruptsWhenWaiting(TmuxAdapter):
    """Sends the interrupt as soon as the fake agent says it is waiting."""

    async def events(self) -> AsyncIterator[AdapterEvent]:
        sent = False
        async for event in super().events():
            yield event
            if not sent and "waiting" in event.payload.get("lines", []):
                sent = True
                await self.interrupt()


async def test_interrupt_stops_the_turn_and_the_run_ends_interrupted(
    tmux_world: World, make_adapter: AdapterMaker, tmp_path: Path
) -> None:
    def interrupting() -> TmuxAdapter:
        return InterruptsWhenWaiting(
            server=make_adapter.server, kinds=make_adapter.kinds, clock=make_adapter().clock
        )

    tmux_world.registry.register("tmux", interrupting, replace=True)
    run = await tmux_world.service.execute(
        agent_id=tmux_world.agent_id, task_id=tmux_world.task_id, prompt="WAIT", cwd=tmp_path
    )

    stored = await stored_run(tmux_world, run.id)
    assert stored.status is RunStatus.INTERRUPTED
    assert stored.exit is not None and stored.exit["terminal_reason"] == "interrupt_sent"
    assert "interrupted" in screen_text(await events_of(tmux_world, run.id))


async def test_close_removes_the_session(
    tmux_world: World, make_adapter: AdapterMaker, tmp_path: Path
) -> None:
    run = await tmux_world.service.execute(
        agent_id=tmux_world.agent_id, task_id=tmux_world.task_id, prompt="x", cwd=tmp_path
    )

    assert not make_adapter.server.has_session(f"run-{run.id}")
