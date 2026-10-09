"""Dialogs that block an agent: a trust question is answered only in labhq's own directories."""

from dataclasses import replace
from pathlib import Path

import pytest

from labhq.adapters.tmux.agents import CLAUDE_CODE
from labhq.adapters.tmux.blocking import blocking_screen, created_by_labhq, selected_line
from labhq.clock import FakeClock
from labhq.db.enums import RunStatus
from labhq.db.models import Run
from tests.adapters.tmux.conftest import AdapterMaker, agent_config
from tests.adapters.tmux.fake_agent import LOGIN_DIALOG, MARK, TRUST_DIALOG
from tests.adapters.tmux.test_tmux_runs import screen_text
from tests.runs.conftest import World
from tests.runs.helpers import events_of, stored_run, use_adapter


async def run_in(world: World, cwd: Path, prompt: str) -> tuple[Run, str]:
    cwd.mkdir(parents=True, exist_ok=True)
    run = await world.service.execute(
        agent_id=world.agent_id, task_id=world.task_id, prompt=prompt, cwd=cwd
    )
    return await stored_run(world, run.id), screen_text(await events_of(world, run.id))


def trust_screen(chosen: int = 0) -> str:
    options = ["No, exit", "Yes, I trust this folder"]
    lines = [f" {MARK} {o}" if n == chosen else f"   {o}" for n, o in enumerate(options)]
    return TRUST_DIALOG.format(cwd="/x", options="\n".join(lines))


def test_the_cursor_starts_on_no_and_moves_to_yes_after_down() -> None:
    assert "No, exit" in (selected_line(trust_screen(0)) or "")
    after_down = selected_line(trust_screen(1)) or ""
    assert "Yes, I trust this folder" in after_down and "No, exit" not in after_down
    assert blocking_screen(CLAUDE_CODE.blocking_screens, trust_screen(1)) is not None


def test_the_captured_trust_screen_is_recognised_and_login_is_not_a_trust_question() -> None:
    shown = blocking_screen(CLAUDE_CODE.blocking_screens, trust_screen())
    assert (
        shown is not None
        and shown.name == "trust-folder"
        and shown.accept_option == "Yes, I trust this folder"
    )
    login = blocking_screen(CLAUDE_CODE.blocking_screens, LOGIN_DIALOG)
    assert login is not None and login.name == "login" and login.accept_option is None
    assert blocking_screen(CLAUDE_CODE.blocking_screens, "all quiet\nthinking") is None


def test_a_dialog_in_old_scrollback_does_not_match() -> None:
    scrollback = trust_screen() + "\n" + "\n".join(f"line {n}" for n in range(40))
    assert blocking_screen(CLAUDE_CODE.blocking_screens, scrollback) is None


def test_only_paths_strictly_inside_the_data_directory_are_labhq_made(tmp_path: Path) -> None:
    data, mine, theirs = tmp_path / "data", tmp_path / "data" / "callcenter", tmp_path / "repo"
    for path in (mine, theirs):
        path.mkdir(parents=True)
    (data / "link").symlink_to(theirs)
    assert created_by_labhq(mine, data)
    assert not created_by_labhq(data, data)
    assert not created_by_labhq(theirs, data)
    assert not created_by_labhq(data / "link", data)
    assert not created_by_labhq(data / ".." / "repo", data)
    assert not created_by_labhq(mine, None)


@pytest.mark.posix_only("the tmux adapter does not run on native Windows (ADR 0003)")
async def test_the_trust_dialog_is_accepted_in_a_directory_labhq_created(
    tmux_world: World, make_adapter: AdapterMaker, tmp_path: Path
) -> None:
    make_adapter.owned_root = tmp_path / "data"

    run, screen = await run_in(tmux_world, tmp_path / "data" / "callcenter", "TRUST")

    assert run.status is RunStatus.SUCCEEDED
    assert "trusted" in screen


@pytest.mark.posix_only("the tmux adapter does not run on native Windows (ADR 0003)")
async def test_the_trust_dialog_fails_the_run_in_any_other_directory_without_a_key(
    tmux_world: World, make_adapter: AdapterMaker, tmp_path: Path
) -> None:
    make_adapter.owned_root = tmp_path / "data"

    run, screen = await run_in(tmux_world, tmp_path / "owners-checkout", "TRUST")

    assert run.status is RunStatus.FAILED
    assert "trusted" not in screen and "exiting without trust" not in screen
    assert "not a directory labhq created" in run.exit["errors"][0]


@pytest.mark.posix_only("the tmux adapter does not run on native Windows (ADR 0003)")
async def test_a_symlink_out_of_the_data_directory_is_not_trusted(
    tmux_world: World, make_adapter: AdapterMaker, tmp_path: Path
) -> None:
    data, checkout = tmp_path / "data", tmp_path / "owners-checkout"
    data.mkdir()
    checkout.mkdir()
    (data / "link").symlink_to(checkout)
    make_adapter.owned_root = data

    run, screen = await run_in(tmux_world, data / "link", "TRUST")

    assert run.status is RunStatus.FAILED
    assert "trusted" not in screen


@pytest.mark.posix_only("the tmux adapter does not run on native Windows (ADR 0003)")
async def test_a_dialog_nobody_may_answer_fails_the_run_even_in_labhq_directories(
    tmux_world: World, make_adapter: AdapterMaker, tmp_path: Path
) -> None:
    make_adapter.owned_root = tmp_path / "data"

    run, _ = await run_in(tmux_world, tmp_path / "data" / "callcenter", "LOGIN")

    assert run.status is RunStatus.FAILED
    assert run.exit["errors"] == ["Claude Code is not logged in"]


@pytest.mark.posix_only("the tmux adapter does not run on native Windows (ADR 0003)")
async def test_a_run_without_progress_fails_with_the_reason(
    tmux_world: World, make_adapter: AdapterMaker, tmp_path: Path
) -> None:
    make_adapter.clock = FakeClock()
    await use_adapter(tmux_world, "tmux", {**agent_config(), "no_progress_seconds": 5})

    run, _ = await run_in(tmux_world, tmp_path / "work", "STALL")

    assert run.status is RunStatus.FAILED
    assert run.exit["terminal_reason"] == "no_progress"
    assert "no progress for 5s" in run.exit["errors"][0]


@pytest.mark.posix_only("the tmux adapter does not run on native Windows (ADR 0003)")
async def test_enter_is_never_sent_when_the_option_cannot_be_selected(
    tmux_world: World, make_adapter: AdapterMaker, tmp_path: Path
) -> None:
    make_adapter.owned_root = tmp_path / "data"
    # Down is replaced by a key the dialog ignores, so the cursor stays on "No, exit".
    for name in make_adapter.kinds.names():
        kind = make_adapter.kinds.get(name)
        screens = tuple(replace(s, select_key="x") for s in kind.blocking_screens)
        make_adapter.kinds.register(replace(kind, blocking_screens=screens), replace=True)

    run, screen = await run_in(tmux_world, tmp_path / "data" / "callcenter", "TRUST")

    assert run.status is RunStatus.FAILED
    assert "could not be selected" in run.exit["errors"][0]
    assert "exiting without trust" not in screen


def test_codex_and_gemini_login_dialogs_are_blocking_screens_nobody_answers() -> None:
    from labhq.adapters.tmux.agents import CODEX, GEMINI

    codex = blocking_screen(CODEX.blocking_screens, "Welcome to Codex\n> Sign in with ChatGPT")
    gemini = blocking_screen(
        GEMINI.blocking_screens, "How would you like to authenticate for this project?"
    )

    assert codex is not None and codex.name == "login" and codex.accept_option is None
    assert gemini is not None and gemini.name == "login" and gemini.accept_option is None
    assert blocking_screen(CODEX.blocking_screens, "• Working (3s • esc to interrupt)") is None
