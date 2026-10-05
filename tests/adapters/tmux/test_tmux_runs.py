"""The fake agent in a real private tmux server: one turn, resume, interrupt."""

import sys
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path

import pytest

from labhq.adapters import AdapterError, AdapterEvent, RunRequest
from labhq.adapters.tmux import (
    AgentKind,
    SessionIdSource,
    TmuxAdapter,
    TurnEnd,
    UsageSource,
    split_session,
)
from labhq.db.enums import RunStatus
from labhq.db.models import Agent
from labhq.memory import AgentMemory
from labhq.prompts import RoleRegistry, builtin_registry
from labhq.runs import RunService
from tests.adapters.tmux.conftest import AdapterMaker, agent_config
from tests.runs.conftest import World
from tests.runs.helpers import events_of, stored_run, task_sessions, use_adapter

pytestmark = pytest.mark.posix_only("the tmux adapter does not run on native Windows (ADR 0003)")


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


async def test_an_unmanaged_ceo_pane_is_left_untouched(
    make_adapter: AdapterMaker, tmp_path: Path
) -> None:
    make_adapter.server.new_session("ceo_claude", cwd=tmp_path, argv=("sleep", "60"), variables={})
    adapter = make_adapter()
    with pytest.raises(AdapterError, match="not managed by labhq"):
        await adapter.start(
            RunRequest(
                run_id=123,
                prompt="hello",
                cwd=tmp_path,
                config=agent_config(),
                persistent_tmux_session="ceo_claude",
            )
        )
    await adapter.close()
    assert make_adapter.server.has_session("ceo_claude")


async def test_ceo_keeps_one_named_pane_and_conversation_across_direct_turns(
    tmux_world: World, make_adapter: AdapterMaker, tmp_path: Path
) -> None:
    script = Path(__file__).with_name("fake_persistent.py")
    kind = AgentKind(
        name="fake-persistent",
        start=(
            sys.executable,
            str(script),
            "--session",
            "{session_id}",
            "--signal",
            "{signal_path}",
            "{prompt}",
        ),
        resume=(
            sys.executable,
            str(script),
            "--resume",
            "{session_id}",
            "--signal",
            "{signal_path}",
            "{prompt}",
        ),
        session_id=SessionIdSource.ASSIGNED,
        interrupt_keys=("C-c",),
        turn_end=TurnEnd.SIGNAL,
        usage_source=UsageSource.SCREEN,
        launch=None,
        hooks=None,
        usage_command=None,
        source="tests/adapters/tmux/fake_persistent.py",
        reply_key="last_assistant_message",
    )
    make_adapter.kinds.register(kind)
    make_adapter.kinds.register(replace(kind, name="fake-other"))
    await use_adapter(tmux_world, "tmux", agent_config("fake-persistent"))
    async with tmux_world.sessions() as db:
        agent = await db.get_one(Agent, tmux_world.agent_id)
        agent.role = "ceo"
        await db.commit()
    roles = RoleRegistry()
    roles.register("ceo", "CEO test rules")
    tmux_world.service = RunService(
        tmux_world.sessions,
        clock=tmux_world.clock,
        registry=tmux_world.registry,
        memory=AgentMemory(tmp_path / "agents"),
        prompts=builtin_registry(roles),
    )

    first = await tmux_world.service.execute(
        agent_id=tmux_world.agent_id, task_id=None, prompt="first question"
    )
    assert make_adapter.server.has_session("ceo_fake_persistent")
    second = await tmux_world.service.execute(
        agent_id=tmux_world.agent_id, task_id=None, prompt="second question"
    )

    before, after = await stored_run(tmux_world, first.id), await stored_run(tmux_world, second.id)
    assert before.status is after.status is RunStatus.SUCCEEDED
    assert after.session_id_before == before.session_id_after
    assert after.session_id_after == before.session_id_after
    assert make_adapter.server.has_session("ceo_fake_persistent")
    assert (
        tmp_path / "agents" / str(tmux_world.agent_id) / ".labhq/skills/ceo-operations/SKILL.md"
    ).exists()
    first_answer = [e for e in await events_of(tmux_world, first.id) if e.kind == "final_answer"]
    second_answer = [e for e in await events_of(tmux_world, second.id) if e.kind == "final_answer"]
    assert "second question" in second_answer[0].payload["text"]
    first_pid = first_answer[0].payload["text"].split()[0]
    assert second_answer[0].payload["text"].split()[0] == first_pid
    assert "CEO test rules" in first_answer[0].payload["text"]
    assert "prompt=second question" in second_answer[0].payload["text"]
    assert "CEO test rules" not in second_answer[0].payload["text"]
    assert "## Your memory" not in second_answer[0].payload["text"]

    await use_adapter(tmux_world, "tmux", agent_config("fake-other"))
    third = await tmux_world.service.execute(
        agent_id=tmux_world.agent_id, task_id=None, prompt="backup question"
    )
    assert make_adapter.server.has_session("ceo_fake_other")
    assert make_adapter.server.has_session("ceo_fake_persistent")
    await use_adapter(tmux_world, "tmux", agent_config("fake-persistent"))
    fourth = await tmux_world.service.execute(
        agent_id=tmux_world.agent_id, task_id=None, prompt="back to primary"
    )
    third_answer = [e for e in await events_of(tmux_world, third.id) if e.kind == "final_answer"]
    fourth_answer = [e for e in await events_of(tmux_world, fourth.id) if e.kind == "final_answer"]
    assert third_answer[0].payload["text"].split()[0] != first_pid
    assert fourth_answer[0].payload["text"].split()[0] == first_pid

    # The tmux session survives a CLI quit; its next turn respawns in the same pane.
    make_adapter.server.send_keys("ceo_fake_persistent", "C-c")
    for _ in range(100):
        if make_adapter.server.pane_state("ceo_fake_persistent").dead:
            break
        await tmux_world.clock.sleep(0.02)
    assert make_adapter.server.pane_state("ceo_fake_persistent").dead
    fifth = await tmux_world.service.execute(
        agent_id=tmux_world.agent_id, task_id=None, prompt="after quit"
    )
    fifth_answer = [e for e in await events_of(tmux_world, fifth.id) if e.kind == "final_answer"]
    assert fifth_answer[0].payload["text"].split()[0] != first_pid
    assert (await stored_run(tmux_world, fifth.id)).session_id_after == before.session_id_after
    assert make_adapter.server.has_session("ceo_fake_persistent")

    # A lost tmux session also starts a fresh pane without reading a stale turn signal.
    make_adapter.server.kill_session("ceo_fake_persistent")
    sixth = await tmux_world.service.execute(
        agent_id=tmux_world.agent_id, task_id=None, prompt="after tmux loss"
    )
    sixth_answer = [e for e in await events_of(tmux_world, sixth.id) if e.kind == "final_answer"]
    assert "after tmux loss" in sixth_answer[0].payload["text"]
    assert (await stored_run(tmux_world, sixth.id)).session_id_after == before.session_id_after
    assert make_adapter.server.has_session("ceo_fake_persistent")
