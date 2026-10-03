import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select

from labhq.clock import FakeClock
from labhq.db import create_engine, session_factory
from labhq.db.enums import (
    AgentStatus,
    ApprovalStatus,
    IncidentStatus,
    MeetingStatus,
    QuestionStatus,
    RiskClass,
    RunStatus,
)
from labhq.db.models import (
    Agent,
    AgentQuestion,
    Approval,
    CostEvent,
    Incident,
    Meeting,
    Project,
    Run,
    Task,
)
from labhq.settings import DATABASE_FILENAME, sqlite_url
from tools import ui_seed


@pytest.fixture
def seed_clock() -> FakeClock:
    return FakeClock(datetime(2026, 10, 2, 9, 0, tzinfo=UTC))


async def test_seeds_every_kind_of_row_the_ui_shows(tmp_path: Path, seed_clock: FakeClock) -> None:
    seeded = await ui_seed.seed_data_dir(tmp_path / "data", seed_clock)

    engine = create_engine(sqlite_url(tmp_path / "data" / DATABASE_FILENAME))
    try:
        async with session_factory(engine)() as db:
            names = list(await db.scalars(select(Project.name).order_by(Project.id)))
            agents = {agent.id: agent for agent in await db.scalars(select(Agent))}
            tasks = await db.scalar(select(func.count()).select_from(Task))
            run = await db.get_one(Run, seeded.runs[0])
            cost = await db.get_one(CostEvent, seeded.cost_events[0])
            heavy = await db.get_one(Approval, seeded.approvals["heavy"])
            light = await db.get_one(Approval, seeded.approvals["light"])
            question = await db.get_one(AgentQuestion, seeded.question)
            incident = await db.get_one(Incident, seeded.incident)
            standup = await db.get_one(Meeting, seeded.meetings["standup"])
            planning = await db.get_one(Meeting, seeded.meetings["planning"])
    finally:
        await engine.dispose()

    assert names == list(ui_seed.PROJECTS)
    assert {agent.adapter for agent in agents.values()} == {"fake"}
    assert agents[seeded.agents[2]].status is AgentStatus.PENDING_APPROVAL
    assert tasks == len(seeded.tasks)
    assert run.status is RunStatus.SUCCEEDED
    assert cost.run_id == run.id
    assert (heavy.risk_class, heavy.type, heavy.status) == (
        RiskClass.HEAVY,
        "push",
        ApprovalStatus.PENDING,
    )
    assert (light.risk_class, light.status) == (RiskClass.LIGHT, ApprovalStatus.PENDING)
    assert question.status is QuestionStatus.PENDING
    assert question.question == ui_seed.QUESTION
    assert incident.status is IncidentStatus.OPEN
    assert incident.details["latest"] == {"/": ui_seed.DISK_FULL_PERCENT}
    assert (standup.kind, standup.status) == ("standup", MeetingStatus.RUNNING)
    assert planning.status is MeetingStatus.ENDED


def test_the_command_prints_the_summary_as_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert ui_seed.main([str(tmp_path / "data")]) == 0

    summary = json.loads(capsys.readouterr().out)
    assert set(summary) == {
        "projects",
        "agents",
        "tasks",
        "runs",
        "cost_events",
        "approvals",
        "question",
        "incident",
    }
    assert set(summary["approvals"]) == {"heavy", "light"}


def test_the_command_refuses_a_data_directory_in_use(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "keep.txt").write_text("someone's data")

    assert ui_seed.main([str(tmp_path / "data")]) == 1
    assert "is not empty" in capsys.readouterr().err
    assert (tmp_path / "data" / "keep.txt").read_text() == "someone's data"
