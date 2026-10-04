"""Seed a throwaway labhq for the UI's end-to-end tests: `python -m tools.ui_seed DATA_DIR`.

Everything goes through the engine's own services with the fake adapter, so the rows look
exactly like the ones a real installation writes: two projects, a manager and a worker, a
task the scheduler runs (one run, its cost and the heavy push approval it asks for), a light
approval, an agent question and an open incident. Nothing calls a model or the network.
The summary is printed as JSON for the Playwright global setup.
"""

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from sqlalchemy import select

from labhq.callcenter.questions.ask import raise_question
from labhq.cli.context import Context
from labhq.cli.demo import bootstrap_repository
from labhq.cli.engine import FAKE_ADAPTER, Engine
from labhq.cli.work import create_agent, create_project, create_task, migrate
from labhq.clock import Clock, SystemClock
from labhq.db import create_engine, session_factory
from labhq.db.enums import AgentStatus, MeetingStatus, TranscriptSource
from labhq.db.models import (
    CostEvent,
    HealthRule,
    Meeting,
    MeetingActionItem,
    MeetingDecision,
    MeetingParticipant,
    MeetingTranscriptEntry,
)
from labhq.health.collector import Reading, collect_local
from labhq.health.incidents import evaluate_rules
from labhq.money import usd_to_micros
from labhq.settings import Settings

PROJECTS = ("atlas", "beacon")
HOST_NAME = "labhq-e2e"
QUESTION = "Should HELLO.md greet in Greek as well as English?"
DISK_METRIC = "disk.percent"
DISK_FULL_PERCENT = 97.0


class SeedError(RuntimeError):
    """The engine did not produce what the UI tests rely on."""


@dataclass(frozen=True)
class Seeded:
    projects: list[int]
    agents: list[int]
    tasks: list[int]
    runs: list[int]
    cost_events: list[int]
    approvals: dict[str, int]
    question: int
    incident: int
    meetings: dict[str, int]


async def _work(context: Context, root: Path) -> tuple[list[int], list[int], list[int]]:
    projects = [
        await create_project(context, name, bootstrap_repository(root / name), None)
        for name in PROJECTS
    ]
    manager = await create_agent(
        context,
        project=PROJECTS[0],
        role="manager",
        title="Project manager",
        adapter=FAKE_ADAPTER,
        status=AgentStatus.ACTIVE,
    )
    worker = await create_agent(
        context,
        project=PROJECTS[0],
        role="worker",
        title="Worker",
        adapter=FAKE_ADAPTER,
        reports_to=manager.id,
        budget=usd_to_micros("1"),
        status=AgentStatus.ACTIVE,
    )
    # Left pending: new agents wait for the owner (plan §5, rule 4).
    newcomer = await create_agent(
        context, project=PROJECTS[1], role="worker", title="Researcher", adapter=FAKE_ADAPTER
    )
    assigned = await create_task(
        context, project=PROJECTS[0], title="Add a HELLO file", assignee=worker.id
    )
    backlog = await create_task(context, project=PROJECTS[1], title="Write the README")
    return (
        [project.id for project in projects],
        [manager.id, worker.id, newcomer.id],
        [assigned.id, backlog.id],
    )


async def _question(context: Context, agent_id: int, task_id: int) -> int:
    async with context.sessions() as db:
        question = await raise_question(
            db, context.clock, agent_id=agent_id, task_id=task_id, text=QUESTION
        )
        await db.commit()
    if question is None:
        raise SeedError("the question was already known; seed an empty data directory")
    return question.id


async def _incident(context: Context) -> int:
    def disk_full() -> list[Reading]:
        return [Reading(DISK_METRIC, DISK_FULL_PERCENT, "/")]

    async with context.sessions() as db:
        samples = await collect_local(db, context.clock, HOST_NAME, probes=(disk_full,))
        now = context.clock.now()
        db.add(
            HealthRule(
                type="threshold",
                name="Disk almost full",
                params={"metric": DISK_METRIC, "comparison": ">", "value": 90},
                host_id=samples[0].host_id,
                reason="Seeded for the UI tests.",
                created_by="tools.ui_seed",
                created_at=now,
                updated_at=now,
            )
        )
        await db.flush()
        changes = await evaluate_rules(db, context.clock)
        await db.commit()
    if len(changes) != 1:
        raise SeedError(f"expected one incident, the rules produced {len(changes)}")
    return changes[0].incident.id


async def _meetings(
    context: Context, project_id: int, agents: list[int], task_id: int
) -> dict[str, int]:
    """A running standup with its conversation, and an ended planning meeting with minutes.

    Rows are written directly: running a meeting is Phase 3's job and needs a model.
    """
    now = context.clock.now()
    async with context.sessions() as db:
        standup = Meeting(
            project_id=project_id,
            kind="standup",
            agenda="What is blocked, and what ships today?",
            status=MeetingStatus.RUNNING,
            created_at=now,
            started_at=now,
        )
        planning = Meeting(
            project_id=project_id,
            kind="planning",
            agenda="Plan the greeting work.",
            status=MeetingStatus.ENDED,
            created_at=now,
            started_at=now,
            ended_at=now,
        )
        db.add_all([standup, planning])
        await db.flush()
        seats = {
            (meeting.id, agent_id): MeetingParticipant(
                meeting_id=meeting.id, agent_id=agent_id, display_name=name
            )
            for meeting in (standup, planning)
            for agent_id, name in zip(agents[:2], ("Project manager", "Worker"), strict=True)
        }
        db.add_all(seats.values())
        await db.flush()
        for agent_id, text in (
            (agents[1], "The HELLO file is written. " + "A very long unbroken word: " + "x" * 300),
            (agents[0], "Nothing is blocked. Ship it today."),
        ):
            db.add(
                MeetingTranscriptEntry(
                    meeting_id=standup.id,
                    participant_id=seats[(standup.id, agent_id)].id,
                    source=TranscriptSource.AGENT,
                    text=text,
                    created_at=now,
                )
            )
        decision = MeetingDecision(meeting_id=planning.id, text="Greet in Greek too", position=1)
        db.add(decision)
        await db.flush()
        db.add(
            MeetingActionItem(
                meeting_id=planning.id,
                decision_id=decision.id,
                text="Add a HELLO file",
                assignee_agent_id=agents[1],
                task_id=task_id,
            )
        )
        await db.commit()
        return {"standup": standup.id, "planning": planning.id}


async def seed(context: Context) -> Seeded:
    """Fill an empty, migrated database. Repositories go under `data_dir/repos`."""
    root = context.settings.data_dir / "repos"
    projects, agents, tasks = await _work(context, root)
    engine = Engine(context)
    report = await engine.run_pass()
    if report.failed or not report.runs or not report.approvals:
        raise SeedError("the scheduler pass did not end in a run with a push approval")
    light = await engine.approvals.request(
        "assign_task", {"task_id": tasks[1], "agent_id": agents[2]}, agent_id=agents[0]
    )
    runs = [run.id for run in report.runs]
    async with context.sessions() as db:
        costs = list(await db.scalars(select(CostEvent.id).where(CostEvent.run_id.in_(runs))))
    if not costs:
        raise SeedError("the run recorded no cost")
    return Seeded(
        projects=projects,
        agents=agents,
        tasks=tasks,
        runs=runs,
        cost_events=costs,
        approvals={"heavy": report.approvals[0].id, "light": light.id},
        question=await _question(context, agents[1], tasks[0]),
        incident=await _incident(context),
        meetings=await _meetings(context, projects[0], agents, tasks[0]),
    )


async def seed_data_dir(data_dir: Path, clock: Clock | None = None) -> Seeded:
    settings = Settings(data_dir=data_dir, database_url=None)
    data_dir.mkdir(parents=True, exist_ok=True)
    # Alembic's env.py runs its own event loop, so it cannot run inside ours.
    await asyncio.to_thread(migrate, settings.resolved_database_url)
    engine = create_engine(settings.resolved_database_url)
    try:
        return await seed(Context(settings, session_factory(engine), clock or SystemClock()))
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_dir", type=Path, help="An empty directory to hold the data.")
    args = parser.parse_args(argv)
    data_dir: Path = args.data_dir.resolve()
    if data_dir.exists() and any(data_dir.iterdir()):
        print(f"error: {data_dir} is not empty", file=sys.stderr)
        return 1
    try:
        seeded = asyncio.run(seed_data_dir(data_dir))
    except SeedError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(asdict(seeded), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
