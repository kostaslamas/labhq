"""An idle persistent pane gives its RAM back; its next turn resumes the same conversation."""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from labhq.adapters.tmux import AgentKind, IdleSuspender, SessionIdSource, TurnEnd, UsageSource
from labhq.clock import Clock, SystemClock
from labhq.db.models import Agent
from labhq.memory import AgentMemory
from labhq.prompts import RoleRegistry, builtin_registry
from labhq.runs import RunService
from tests.adapters.tmux.conftest import AdapterMaker, agent_config
from tests.runs.conftest import World
from tests.runs.helpers import events_of, stored_run, use_adapter

pytestmark = pytest.mark.posix_only("the tmux adapter does not run on native Windows (ADR 0003)")

SESSION = "ceo_fake_persistent"


class SkewedClock:
    """The system clock, moved forward by a test instead of waiting."""

    def __init__(self) -> None:
        self.skew = timedelta(0)
        self._real: Clock = SystemClock()

    def now(self) -> datetime:
        return self._real.now() + self.skew

    async def sleep(self, seconds: float) -> None:
        await self._real.sleep(seconds)


def persistent_kind() -> AgentKind:
    script = str(Path(__file__).with_name("fake_persistent.py"))
    return AgentKind(
        name="fake-persistent",
        start=(
            sys.executable,
            script,
            "--session",
            "{session_id}",
            "--signal",
            "{signal_path}",
            "{prompt}",
        ),
        resume=(
            sys.executable,
            script,
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


async def ceo_service(world: World, make_adapter: AdapterMaker, tmp_path: Path) -> RunService:
    make_adapter.kinds.register(persistent_kind())
    await use_adapter(world, "tmux", agent_config("fake-persistent"))
    async with world.sessions() as db:
        (await db.get_one(Agent, world.agent_id)).role = "ceo"
        await db.commit()
    roles = RoleRegistry()
    roles.register("ceo", "CEO test rules")
    return RunService(
        world.sessions,
        clock=world.clock,
        registry=world.registry,
        memory=AgentMemory(tmp_path / "agents"),
        prompts=builtin_registry(roles),
    )


async def test_a_pane_idle_past_the_limit_is_stopped_and_resumes_the_same_session(
    tmux_world: World, make_adapter: AdapterMaker, tmp_path: Path
) -> None:
    clock = SkewedClock()
    make_adapter.clock = clock
    service = await ceo_service(tmux_world, make_adapter, tmp_path)
    suspender = IdleSuspender(
        make_adapter.server, clock, idle_seconds=1800, check_every=timedelta(0)
    )
    first = await service.execute(agent_id=tmux_world.agent_id, task_id=None, prompt="first")

    clock.skew = timedelta(seconds=1799)
    assert await suspender.suspend_idle() == []
    assert not make_adapter.server.pane_state(SESSION).dead

    clock.skew = timedelta(seconds=1801)
    assert await suspender.suspend_idle() == [SESSION]
    for _ in range(100):
        if make_adapter.server.pane_state(SESSION).dead:
            break
        await clock.sleep(0.05)
    assert make_adapter.server.pane_state(SESSION).dead
    assert make_adapter.server.has_session(SESSION)

    second = await service.execute(agent_id=tmux_world.agent_id, task_id=None, prompt="second")

    before, after = await stored_run(tmux_world, first.id), await stored_run(tmux_world, second.id)
    assert after.session_id_before == before.session_id_after
    assert after.session_id_after == before.session_id_after
    answers = [e for e in await events_of(tmux_world, second.id) if e.kind == "final_answer"]
    assert f"session={before.session_id_after.split(':', 1)[1]}" in answers[0].payload["text"]
    assert answers[0].payload["text"].rstrip().endswith("second")
    # A new process: the stopped CLI really went away.
    first_answer = [e for e in await events_of(tmux_world, first.id) if e.kind == "final_answer"]
    assert answers[0].payload["text"].split()[0] != first_answer[0].payload["text"].split()[0]


async def test_zero_never_stops_a_pane_and_a_running_turn_is_never_idle(
    tmux_world: World, make_adapter: AdapterMaker, tmp_path: Path
) -> None:
    clock = SkewedClock()
    make_adapter.clock = clock
    service = await ceo_service(tmux_world, make_adapter, tmp_path)
    await service.execute(agent_id=tmux_world.agent_id, task_id=None, prompt="first")

    clock.skew = timedelta(days=2)
    assert await IdleSuspender(make_adapter.server, clock, idle_seconds=0).suspend_idle() == []
    assert not make_adapter.server.pane_state(SESSION).dead
