"""`read_screen`: read-only, by agent name or task, text only."""

from pathlib import Path

import pytest

from labhq.callcenter.calls import CallTools, NoInterrupter
from labhq.callcenter.screens import ScreenLog, ScreenReader
from labhq.db.enums import RunStatus
from labhq.db.models import Agent, Run, RunEvent
from tests.callcenter.screens.conftest import Office, SpyServer, until

pytestmark = pytest.mark.posix_only("the tmux adapter does not run on native Windows (ADR 0003)")


def _tools(office: Office, *, screens: bool = True) -> CallTools:
    reader = office.reader if screens else None
    return CallTools(office.sessions, office.clock, NoInterrupter(), call_id=1, screens=reader)


async def test_it_reads_the_screen_by_agent_name_or_by_task(office: Office) -> None:
    tools = _tools(office)

    by_name = await tools.read_screen({"agent": "  manager "})
    by_task = await tools.read_screen({"task_id": office.task_id})

    for text in (by_name, by_task):
        assert "read without sending it anything" in text
        assert "manager: working on the login form" in text
    assert by_name.startswith("Manager.")
    assert office.server.keys_sent() == []


async def test_it_is_a_read_only_tool_with_no_required_argument(office: Office) -> None:
    [spec] = [spec for spec in _tools(office).specs() if spec.name == "read_screen"]

    assert spec.read_only
    assert set(spec.input_schema["properties"]) == {"agent", "task_id"}
    assert "required" not in spec.input_schema


async def test_it_says_when_there_is_nothing_to_read(office: Office) -> None:
    async with office.sessions() as db:
        now = office.clock.now()
        for title in ("Worker", "Twin", "Twin"):
            db.add(
                Agent(role="worker", title=title, adapter="fake", created_at=now, updated_at=now)
            )
        await db.commit()
    tools = _tools(office)

    assert await tools.read_screen({}) == "Name an agent or a task."
    assert "No agent is called Nobody" in await tools.read_screen({"agent": "Nobody"})
    assert "Several agents are called Twin" in await tools.read_screen({"agent": "Twin"})
    assert "not running in tmux" in await tools.read_screen({"agent": "Worker"})
    assert "tmux is not installed" in await _tools(office, screens=False).read_screen({})


async def test_it_lists_and_reads_any_named_session_on_the_private_server(office: Office) -> None:
    office.server.new_session(
        "ceo_codex",
        cwd=office.workdir,
        argv=("sh", "-c", "printf 'CEO finished\\n'"),
        variables={},
    )
    await until(lambda: office.server.pane_state("ceo_codex").dead, "CEO pane to exit")
    tools = _tools(office)

    listed = await tools.list_tmux_sessions({})
    read = await tools.read_tmux_session({"name": "ceo_codex"})

    assert f"run-{office.run_id}" in listed and "ceo_codex" in listed
    assert "CEO finished" in read
    assert "read without sending it anything" in read
    assert "no tmux session named" in await tools.read_tmux_session({"name": "absent"})
    assert office.server.keys_sent() == []


async def test_no_server_means_no_named_sessions(spy_server: SpyServer, tmp_path: Path) -> None:
    reader = ScreenReader(spy_server, ScreenLog(tmp_path / "screens"))

    assert await reader.list_sessions() == []
    assert await reader.capture_session("ceo_codex") is None


async def test_read_screen_finds_a_running_ceo_in_its_named_pane(office: Office) -> None:
    office.server.new_session(
        "ceo_codex",
        cwd=office.workdir,
        argv=("sh", "-c", "printf 'CEO reviewing projects\\n'; exec sleep 60"),
        variables={},
    )
    await until(
        lambda: "CEO reviewing projects" in office.server.capture("ceo_codex"),
        "CEO pane output",
    )
    async with office.sessions() as db:
        now = office.clock.now()
        ceo = Agent(
            role="ceo",
            title="CEO",
            adapter="tmux",
            config={"agent": "claude-code"},
            created_at=now,
            updated_at=now,
        )
        db.add(ceo)
        await db.flush()
        run = Run(
            agent_id=ceo.id,
            adapter="tmux",
            status=RunStatus.RUNNING,
            created_at=now,
            started_at=now,
        )
        db.add(run)
        await db.flush()
        db.add(
            RunEvent(
                run_id=run.id,
                seq=1,
                kind="agent",
                payload={"kind": "codex"},
                created_at=now,
            )
        )
        await db.commit()

    read = await _tools(office).read_screen({"agent": "CEO"})

    assert "CEO reviewing projects" in read
    assert office.server.keys_sent() == []
