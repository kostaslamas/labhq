"""`read_screen`: read-only, by agent name or task, text only."""

import pytest

from labhq.callcenter.calls import CallTools, NoInterrupter
from labhq.db.models import Agent
from tests.callcenter.screens.conftest import Office

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
