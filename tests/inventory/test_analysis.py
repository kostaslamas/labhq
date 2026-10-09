"""Analysis runs for one project, after the owner confirms a shown estimate, on another kind."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.adapters import AdapterEvent, AdapterRegistry, FakeAdapter, FakeScript, default_registry
from labhq.approvals import default_actions, default_executors
from labhq.clock import FakeClock
from labhq.db.enums import ApprovalStatus, RiskClass
from labhq.db.models import Approval, CeoReport, Run
from labhq.inventory.analysis import (
    ANALYSE_PROJECT,
    AnalysePayload,
    Analyses,
    AnalysisEngine,
    AnalysisError,
)
from labhq.inventory.chooser import NoRunnerError, Runner, choose_runner
from labhq.inventory.register import AnalysisEngine as _Registered  # noqa: F401
from labhq.inventory.settings import InventorySettings
from tests.inventory import stores_fixture as fx
from tests.inventory.conftest import Scan, make_repo

REPORT = "## What each agent did\nIt added the party screen."


class Answering(FakeAdapter):
    async def events(self) -> AsyncIterator[AdapterEvent]:
        async for event in super().events():
            if event.kind == "result":
                yield AdapterEvent("result", {**event.payload, "result": REPORT})
                continue
            yield event


FAKE = {"fake": Runner("fake", "fake")}
SETTINGS = {"analysis_kind_order": ["fake"], "no_login_kinds": ["fake"]}


@pytest.fixture
def script() -> FakeScript:
    return FakeScript()


@pytest.fixture
def registry(script: FakeScript) -> AdapterRegistry:
    adapters = default_registry.copy()
    adapters.register("fake", lambda: Answering(script), replace=True)
    return adapters


def analyses(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock, scanner: Scan, **settings: object
) -> Analyses:
    return Analyses(
        sessions,
        clock=clock,
        scanner=scanner(),
        settings=InventorySettings(**{**SETTINGS, **settings}),  # type: ignore[arg-type]
        runners=FAKE,
    )


async def test_the_request_shows_an_estimate_and_runs_nothing(
    home: Path,
    tmp_path: Path,
    scanner: Scan,
    sessions: async_sessionmaker[AsyncSession],
    clock: FakeClock,
    script: FakeScript,
) -> None:
    party = make_repo(tmp_path / "party")
    fx.claude(home, party)

    request = await analyses(sessions, clock, scanner).request("party")

    assert request.payload.kind == "fake"
    assert request.payload.cost_micros > 0 and request.estimate.tokens > 0
    assert "party" in request.text and "fake" in request.text and "$" in request.text
    assert f"approval {request.approval_id}" in request.text
    async with sessions() as db:
        approval = await db.get_one(Approval, request.approval_id)
        assert (approval.type, approval.status) == (ANALYSE_PROJECT, ApprovalStatus.PENDING)
        assert list(await db.scalars(select(Run))) == []
    assert script.requests == []


async def test_only_a_named_project_can_be_analysed(
    home: Path,
    tmp_path: Path,
    scanner: Scan,
    sessions: async_sessionmaker[AsyncSession],
    clock: FakeClock,
) -> None:
    fx.claude(home, make_repo(tmp_path / "party"))

    with pytest.raises(AnalysisError, match="no project named"):
        await analyses(sessions, clock, scanner).request("nothing")
    with pytest.raises(AnalysisError, match="no project named"):
        await analyses(sessions, clock, scanner).request("")


async def test_the_approved_analysis_runs_on_the_fake_adapter_and_writes_an_md_file(
    home: Path,
    tmp_path: Path,
    scanner: Scan,
    sessions: async_sessionmaker[AsyncSession],
    clock: FakeClock,
    registry: AdapterRegistry,
    script: FakeScript,
    database_url: str,
) -> None:
    party = make_repo(tmp_path / "party")
    other = make_repo(tmp_path / "other")
    (party / "dirty.txt").write_text("unfinished\n", encoding="utf-8")
    fx.claude(home, party)
    fx.codex(home, other)
    request = await analyses(sessions, clock, scanner).request("party")
    engine = AnalysisEngine(
        clock=clock,
        registry=registry,
        settings=lambda: InventorySettings(**SETTINGS),  # type: ignore[arg-type]
        runners=FAKE,
        database_url=lambda: database_url,
        data_dir=lambda: tmp_path / "data",
    )

    result = await engine.analyse(request.payload)

    path = Path(result["path"])
    assert path.parent == tmp_path / "data" / "inventory" / "analyses"
    text = path.read_text(encoding="utf-8")
    assert REPORT in text and "party" in text
    (run_request,) = script.requests
    prompt = run_request.prompt
    assert "What is unfinished" in prompt and "first commit" in prompt
    assert "dirty.txt" in prompt and fx.SECRET_TEXT in prompt  # this project's transcript tail
    assert "#### codex" not in prompt  # another project's session is not read
    assert run_request.tools == () and run_request.cwd != party
    async with sessions() as db:
        (report,) = list(await db.scalars(select(CeoReport)))
    assert str(path) in report.text


async def test_the_analysis_is_not_run_by_the_tool_that_made_the_sessions(
    home: Path,
    tmp_path: Path,
    scanner: Scan,
    sessions: async_sessionmaker[AsyncSession],
    clock: FakeClock,
) -> None:
    fx.claude(home, make_repo(tmp_path / "party"))
    only_original = Runner("claude-code", "tmux", {"agent": "claude-code"})
    settings = InventorySettings(
        analysis_kind_order=["claude-code"], no_login_kinds=["claude-code"]
    )

    request = Analyses(
        sessions,
        clock=clock,
        scanner=scanner(),
        settings=settings,
        runners={"claude-code": only_original},
    )

    with pytest.raises(NoRunnerError, match="made the sessions"):
        await request.request("party")

    allowed = InventorySettings(
        analysis_kind_order=["claude-code"],
        no_login_kinds=["claude-code"],
        allow_original_tool=True,
    )
    async with sessions() as db:
        choice = await choose_runner(
            db,
            clock,
            allowed,
            original_tools={"claude-code"},
            runners={"claude-code": only_original},
        )
    assert choice.runner.name == "claude-code"


async def test_a_failed_analysis_run_writes_no_file(
    home: Path,
    tmp_path: Path,
    scanner: Scan,
    sessions: async_sessionmaker[AsyncSession],
    clock: FakeClock,
    registry: AdapterRegistry,
    script: FakeScript,
    database_url: str,
) -> None:
    fx.claude(home, make_repo(tmp_path / "party"))
    request = await analyses(sessions, clock, scanner).request("party")
    script.subtype, script.is_error, script.terminal_reason = "error_max_turns", True, None
    engine = AnalysisEngine(
        clock=clock,
        registry=registry,
        runners=FAKE,
        database_url=lambda: database_url,
        data_dir=lambda: tmp_path / "data",
        settings=lambda: InventorySettings(**SETTINGS),  # type: ignore[arg-type]
    )

    with pytest.raises(AnalysisError, match="ended"):
        await engine.analyse(request.payload)

    assert not (tmp_path / "data" / "inventory" / "analyses").exists()


def test_analysis_is_a_light_approval_with_an_executor() -> None:
    assert default_actions.get(ANALYSE_PROJECT).risk_class is RiskClass.LIGHT
    assert default_executors.get(ANALYSE_PROJECT).validate is not None
    with pytest.raises(ValueError):
        AnalysePayload.model_validate({"project": "x"})
