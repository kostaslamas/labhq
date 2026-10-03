"""The Codex entry passes the adapter contract against the fake `codex` in a real tmux server.

Resume, interrupt and the push guard are also checked through the run service, where the
stored session, its `cwd` and the run's status are what the engine relies on.
"""

import json
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import replace
from pathlib import Path

import pytest

from labhq.adapters import AdapterEvent, RunRequest, contract
from labhq.adapters.contract import run_once
from labhq.adapters.tmux import TmuxAdapter, TmuxServer, get_tmux_settings, split_session
from labhq.adapters.tmux.agents import CODEX, LAUNCHES, LaunchContext, codex_config
from labhq.clock import SystemClock
from labhq.db.enums import RunStatus
from labhq.settings import get_settings
from labhq.worktrees import Worktree, Worktrees
from labhq.worktrees.git import run_git
from tests.adapters.codex_harness import (
    CODEX_CONFIG,
    FakeCodex,
    fake_codex,  # noqa: F401  (fixture)
    install_fake_codex,
)
from tests.adapters.tmux.conftest import FAST, require_tmux
from tests.adapters.tmux.test_tmux_runs import screen_text
from tests.runs.conftest import World, sessions, world  # noqa: F401  (fixtures)
from tests.runs.helpers import events_of, stored_run, task_sessions, use_adapter
from tests.worktrees.conftest import isolated_git, remote, repo  # noqa: F401  (fixtures)
from tests.worktrees.gitrepo import commit_file

pytestmark = pytest.mark.posix_only("the tmux adapter does not run on native Windows (ADR 0003)")


@pytest.fixture
def default_tmux(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The registered `tmux` adapter, as `python -m labhq.adapters.contract` builds it."""
    require_tmux()
    environ, _ = install_fake_codex(tmp_path / "runner")
    socket = f"labhq-test-{uuid.uuid4().hex[:12]}"
    monkeypatch.setenv("PATH", environ["PATH"])
    monkeypatch.setenv("LABHQ_TMUX_SOCKET", socket)
    monkeypatch.setenv("LABHQ_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(contract, "EXTRA_CONFIG", {})
    get_settings.cache_clear()
    get_tmux_settings.cache_clear()
    try:
        yield
    finally:
        TmuxServer(socket=socket, state_dir=tmp_path / "data" / "tmux").kill_server()
        get_settings.cache_clear()
        get_tmux_settings.cache_clear()


def test_the_contract_runner_passes_every_check_on_tmux_codex(
    default_tmux: None, capsys: pytest.CaptureFixture[str]
) -> None:
    status = contract.main(["tmux:codex", "--config", json.dumps(FAST)])

    out = capsys.readouterr().out
    assert [line.split()[0:2] for line in out.splitlines()[:3]] == [
        ["PASS", "completes"],
        ["PASS", "interrupt"],
        ["PASS", "resume"],
    ]
    assert status == 0
    assert contract.EXTRA_CONFIG["agent"] == "codex"


@pytest.fixture
async def codex_world(world: World, fake_codex: FakeCodex) -> World:  # noqa: F811
    world.registry.register("tmux", fake_codex.adapter, replace=True)
    await use_adapter(world, "tmux", CODEX_CONFIG)
    return world


async def test_a_second_run_resumes_the_stored_codex_session_in_the_same_cwd(
    codex_world: World,
    fake_codex: FakeCodex,  # noqa: F811
    tmp_path: Path,
) -> None:
    first = await codex_world.service.execute(
        agent_id=codex_world.agent_id,
        task_id=codex_world.task_id,
        prompt="Remember the codeword AURORA-7 and reply with the single word OK.",
        cwd=tmp_path,
    )
    # No cwd: the run service takes the stored one, as resume needs.
    second = await codex_world.service.execute(
        agent_id=codex_world.agent_id, task_id=codex_world.task_id, prompt="What was the codeword?"
    )

    before = await stored_run(codex_world, first.id)
    after = await stored_run(codex_world, second.id)
    assert (before.status, after.status) == (RunStatus.SUCCEEDED, RunStatus.SUCCEEDED)
    kind, session = split_session(before.session_id_after)
    (stored,) = fake_codex.session_files()
    assert (kind, session) == ("codex", stored.stem)
    assert after.session_id_before == after.session_id_after == before.session_id_after
    text = screen_text(await events_of(codex_world, second.id))
    assert f"directory: {tmp_path}" in text
    assert "• AURORA-7" in text
    (row,) = await task_sessions(codex_world)
    assert (row.session_id, row.cwd) == (before.session_id_after, str(tmp_path))


class InterruptsOnReply(TmuxAdapter):
    """Sends the interrupt on the first line of Codex's own output."""

    async def events(self) -> AsyncIterator[AdapterEvent]:
        sent = False
        async for event in super().events():
            yield event
            if event.kind == "assistant" and not sent:
                sent = True
                await self.interrupt()


async def test_interrupt_ends_the_codex_run_as_interrupted(
    codex_world: World,
    fake_codex: FakeCodex,  # noqa: F811
    tmp_path: Path,
) -> None:
    def interrupting() -> TmuxAdapter:
        return InterruptsOnReply(
            server=fake_codex.server,
            kinds=fake_codex.kinds,
            clock=SystemClock(),
            environ=fake_codex.environ,
        )

    codex_world.registry.register("tmux", interrupting, replace=True)
    run = await codex_world.service.execute(
        agent_id=codex_world.agent_id,
        task_id=codex_world.task_id,
        prompt=contract.INTERRUPT_PROMPT,
        cwd=tmp_path,
    )

    stored = await stored_run(codex_world, run.id)
    assert stored.status is RunStatus.INTERRUPTED
    assert stored.exit is not None and stored.exit["terminal_reason"] == "interrupt_sent"
    text = screen_text(await events_of(codex_world, run.id))
    assert "■ Conversation interrupted" in text
    # No usage command is sent into an interrupted turn.
    assert "5h limit:" not in text


@pytest.fixture
def worktree(repo: Path, tmp_path: Path) -> Worktree:  # noqa: F811
    worktree = Worktrees(repo, tmp_path / "worktrees").create(9, "push attempt")
    commit_file(worktree.path, "work.txt")
    return worktree


def remote_refs(bare: Path) -> str:
    return run_git("for-each-ref", "--format=%(refname) %(objectname)", cwd=bare)


async def push_screen(codex: FakeCodex, worktree: Worktree) -> str:
    request = RunRequest(prompt="Run git push origin HEAD", cwd=worktree.path, config=CODEX_CONFIG)
    events, _ = await run_once(codex.adapter(), request)
    return screen_text(events)


async def test_the_guard_hook_denies_git_push_from_the_codex_worktree(
    fake_codex: FakeCodex,  # noqa: F811
    worktree: Worktree,
    remote: Path,  # noqa: F811
) -> None:
    before = remote_refs(remote)

    screen = await push_screen(fake_codex, worktree)

    assert "Command blocked by PreToolUse hook: Publishing is reserved" in screen
    assert "• Ran git push" not in screen
    assert remote_refs(remote) == before


async def test_without_the_hook_git_push_still_fails_at_the_transport(
    fake_codex: FakeCodex,  # noqa: F811
    worktree: Worktree,
    remote: Path,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The turn signal stays; only the guard hook is replaced by one that allows everything.
    def no_guard(context: LaunchContext) -> list[str]:
        return codex_config(replace(context, guard_hook="true"))

    monkeypatch.setitem(LAUNCHES, "codex_no_guard", no_guard)
    fake_codex.kinds.register(replace(CODEX, launch="codex_no_guard", hooks=None), replace=True)
    before = remote_refs(remote)

    screen = await push_screen(fake_codex, worktree)

    assert "• Ran git push origin HEAD" in screen
    assert "exited 0" not in screen
    assert remote_refs(remote) == before
