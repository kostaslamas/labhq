"""A real private tmux server per test, and the fake agent kinds that run in it."""

import os
import shutil
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from labhq.adapters.tmux import (
    AgentKind,
    AgentKinds,
    SessionIdSource,
    TmuxAdapter,
    TmuxServer,
    TurnEnd,
    UsageSource,
    default_kinds,
)
from labhq.adapters.tmux.agents import CLAUDE_BLOCKING_SCREENS
from labhq.clock import Clock, SystemClock
from tests.runs.conftest import World, sessions, world  # noqa: F401  (fixtures)
from tests.runs.helpers import use_adapter
from tests.worktrees.conftest import isolated_git, remote, repo  # noqa: F401  (fixtures)

FAKE_AGENT = Path(__file__).with_name("fake_agent.py")
FAST = {
    "poll_seconds": 0.05,
    "quiescence_seconds": 0.5,
    "interrupt_settle_seconds": 0.5,
    "usage_settle_seconds": 0.3,
    "usage_timeout_seconds": 10,
}


def require_tmux() -> str:
    """tmux or a failure: a tmux test that skips would pass while proving nothing."""
    found = shutil.which("tmux")
    if found is None:
        pytest.fail("tmux is not installed; the tmux adapter tests need it (CI installs it)")
    return found


def fake_kind(name: str, *, hook: bool) -> AgentKind:
    hook_words = ("--hook", "{guard_hook}") if hook else ()
    script = (sys.executable, str(FAKE_AGENT))
    return AgentKind(
        name=name,
        start=(*script, "--session", "{session_id}", *hook_words, "{prompt}"),
        resume=(*script, "--resume", "{session_id}", *hook_words, "{prompt}"),
        session_id=SessionIdSource.ASSIGNED,
        interrupt_keys=("C-c",),
        turn_end=TurnEnd.PATTERN,
        turn_end_pattern=r"^LABHQ-FAKE-TURN-END$",
        usage_source=UsageSource.SCREEN,
        launch=None,
        hooks="--hook" if hook else None,
        usage_command="/usage",
        source="tests/adapters/tmux/fake_agent.py",
        blocking_screens=CLAUDE_BLOCKING_SCREENS,
    )


def fake_kinds() -> AgentKinds:
    kinds = default_kinds.copy()
    kinds.register(fake_kind("fake-agent", hook=True))
    kinds.register(fake_kind("fake-agent-nohook", hook=False))
    return kinds


def agent_config(kind: str = "fake-agent") -> dict[str, object]:
    return {"agent": kind, **FAST}


@pytest.fixture
def tmux_server(tmp_path: Path) -> Iterator[TmuxServer]:
    require_tmux()
    server = TmuxServer(socket=f"labhq-test-{uuid.uuid4().hex[:12]}", state_dir=tmp_path / "tmux")
    try:
        yield server
    finally:
        server.kill_server()


@pytest.fixture
def make_adapter(tmux_server: TmuxServer) -> "AdapterMaker":
    return AdapterMaker(tmux_server)


class AdapterMaker:
    """Builds adapters on the test's server, reading the environment at call time."""

    def __init__(self, server: TmuxServer) -> None:
        self.server = server
        self.kinds = fake_kinds()
        self.owned_root: Path | None = None
        self.clock: Clock = SystemClock()

    def __call__(self) -> TmuxAdapter:
        return TmuxAdapter(
            server=self.server,
            kinds=self.kinds,
            clock=self.clock,
            environ=dict(os.environ),
            owned_root=self.owned_root,
        )


@pytest.fixture
async def tmux_world(world: World, make_adapter: AdapterMaker) -> World:  # noqa: F811
    """The run tests' world, with its agent on the tmux adapter running the fake agent."""
    world.registry.register("tmux", make_adapter, replace=True)
    await use_adapter(world, "tmux", agent_config())
    return world
