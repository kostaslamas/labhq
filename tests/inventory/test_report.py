"""The CEO gets one report per project; the Call Center speaks the short version."""

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.adapters.tmux import default_kinds
from labhq.clock import FakeClock
from labhq.db.models import CeoReport, UsageReading
from labhq.inventory.login import login_of, tool_statuses
from labhq.inventory.report import spoken
from labhq.inventory.service import scan_and_report
from labhq.inventory.settings import InventorySettings
from tests.db.factories import project_agent_task
from tests.inventory import stores_fixture as fx
from tests.inventory.conftest import FakeProcess, Scan, make_repo


def runner(code: int, output: str = ""):
    return lambda argv, timeout: (code, output)


async def test_the_ceo_receives_one_report_per_project_with_every_fact(
    home: Path,
    tmp_path: Path,
    scanner: Scan,
    sessions: async_sessionmaker[AsyncSession],
    clock: FakeClock,
) -> None:
    party = make_repo(tmp_path / "work" / "party")
    (party / "dirty.txt").write_text("x", encoding="utf-8")
    fx.claude(home, party)
    fx.opencode(home, [("ses_1", str(party), None, None)])
    plain = tmp_path / "scratch"
    plain.mkdir()
    fx.codex(home, plain)

    async with sessions() as db:
        result = await scan_and_report(
            db,
            clock,
            scanner=scanner([FakeProcess(5, ["claude"], party)]),
            report=True,
            run=runner(0, "Logged in as owner@example.com"),
            which=lambda name: f"/bin/{name}",
        )
        await db.commit()
        reports = list(await db.scalars(select(CeoReport).order_by(CeoReport.id)))

    assert len(reports) == len(result.report_ids) == 2
    party_report = next(r.text for r in reports if "Project party" in r.text)
    assert "branch main, 1 dirty files" in party_report
    assert "claude-code" in party_report and "opencode ses_1" in party_report
    assert "idle" in party_report or "active now" in party_report
    assert "-> " in party_report  # a proposed action per session
    assert "logged in as owner@example.com" in party_report
    assert any("no repo" in r.text for r in reports)


async def test_a_scan_without_a_report_files_nothing(
    home: Path,
    tmp_path: Path,
    scanner: Scan,
    sessions: async_sessionmaker[AsyncSession],
    clock: FakeClock,
) -> None:
    fx.claude(home, make_repo(tmp_path / "party"))

    async with sessions() as db:
        result = await scan_and_report(db, clock, scanner=scanner(), report=False)
        assert list(await db.scalars(select(CeoReport))) == []

    assert result.report_ids == []


def test_the_spoken_answer_counts_open_and_saved_sessions_per_project(
    home: Path, tmp_path: Path, scanner: Scan
) -> None:
    party = make_repo(tmp_path / "games" / "party")
    chess = make_repo(tmp_path / "games" / "chess")
    fx.claude(home, party)
    fx.codex(home, party)
    fx.gemini(home, chess)

    text = spoken(scanner([FakeProcess(5, ["claude"], party)]).scan())

    assert "party: 1 open, 1 saved" in text
    assert "chess: 0 open, 1 saved" in text
    assert "folder manager" in text and "games" in text


def test_an_empty_machine_says_so(scanner: Scan) -> None:
    assert spoken(scanner().scan()) == "I found no agent sessions on this machine."


def test_login_comes_from_the_status_command_alone() -> None:
    claude = default_kinds.get("claude-code")
    cursor = default_kinds.get("cursor-agent")
    gemini = default_kinds.get("gemini")

    assert login_of(claude, runner(0), 5) == (True, None)
    assert login_of(claude, runner(1), 5) == (False, None)
    assert login_of(cursor, runner(0, "Not logged in"), 5) == (False, None)
    assert login_of(cursor, runner(0, "Logged in: me@x.org"), 5) == (True, "me@x.org")
    assert login_of(gemini, runner(0), 5) == (None, None)
    assert login_of(claude, lambda argv, timeout: None, 5) == (None, None)


async def test_tool_status_adds_the_plan_room_from_usage_readings(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock
) -> None:
    async with sessions() as db:
        _, agent, _ = await project_agent_task(db, clock)
        db.add(
            UsageReading(
                agent_id=agent.id,
                agent_kind="codex",
                unit="percent",
                value=80.0,
                window="5h",
                source="screen",
                created_at=clock.now(),
            )
        )
        await db.commit()
        statuses = await tool_statuses(
            db,
            default_kinds,
            clock,
            InventorySettings(),
            run=runner(0),
            which=lambda name: f"/bin/{name}" if name in ("codex", "gemini") else None,
        )

    by_tool = {s.tool: s for s in statuses}
    assert set(by_tool) == {"codex", "gemini"}
    assert (
        by_tool["codex"].logged_in,
        by_tool["codex"].plan,
        by_tool["codex"].plan_used_percent,
    ) == (
        True,
        "stop",
        80.0,
    )
    assert (by_tool["gemini"].logged_in, by_tool["gemini"].plan) == (None, None)
