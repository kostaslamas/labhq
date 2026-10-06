"""Root tasks the CEO reported to the owner, for the CEO chat's end-to-end spec.

`python -m tools.e2e_ceo_report DATA_DIR TITLE...` adds them to the seeded data directory
(`tools.ui_seed`) and prints `{title: task_id}` as JSON; a CEO is created on the fake adapter
only when none is configured yet. `--cancel ID...` cancels the spec's tasks afterwards, so a
task it accepted never shows on another spec's Today list.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import select

from labhq.ceoreports import record_report
from labhq.cli.context import Context
from labhq.cli.engine import FAKE_ADAPTER
from labhq.clock import SystemClock
from labhq.db import create_engine, session_factory
from labhq.db.enums import AgentStatus, TaskStatus
from labhq.db.models import Agent, Project, Task
from labhq.hierarchy import CEO, MANAGER
from labhq.settings import Settings


async def _ceo(context: Context) -> Agent:
    async with context.sessions() as db:
        ceo = await db.scalar(
            select(Agent).where(Agent.role == CEO, Agent.status != AgentStatus.RETIRED)
        )
        if ceo is not None:
            return ceo
        now = context.clock.now()
        ceo = Agent(
            role=CEO,
            title="CEO",
            adapter=FAKE_ADAPTER,
            status=AgentStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        db.add(ceo)
        await db.commit()
        return ceo


async def add_reports(context: Context, titles: list[str]) -> dict[str, int]:
    ceo = await _ceo(context)
    created: dict[str, int] = {}
    async with context.sessions() as db:
        manager = await db.scalar(select(Agent).where(Agent.role == MANAGER).order_by(Agent.id))
        project = await db.scalar(select(Project).order_by(Project.id))
        if manager is None or project is None:
            raise SystemExit("error: seed the data directory with tools.ui_seed first")
        for title in titles:
            now = context.clock.now()
            task = Task(
                project_id=project.id,
                title=title,
                assignee_id=manager.id,
                status=TaskStatus.IN_REVIEW,
                created_at=now,
                updated_at=now,
            )
            db.add(task)
            await db.flush()
            await record_report(
                db,
                context.clock,
                agent_id=ceo.id,
                text=f"T{task.id} {title} is done and waits for your decision.",
                refs=[f"T{task.id}"],
                task_id=task.id,
            )
            created[title] = task.id
        await db.commit()
    return created


async def cancel(context: Context, task_ids: list[int]) -> dict[str, int]:
    async with context.sessions() as db:
        for task_id in task_ids:
            task = await db.get_one(Task, task_id)
            task.status, task.updated_at = TaskStatus.CANCELLED, context.clock.now()
        await db.commit()
    return {}


async def _main(data_dir: Path, values: list[str], cancelling: bool) -> dict[str, int]:
    settings = Settings(data_dir=data_dir, database_url=None)
    engine = create_engine(settings.resolved_database_url)
    context = Context(settings, session_factory(engine), SystemClock())
    try:
        if cancelling:
            return await cancel(context, [int(value) for value in values])
        return await add_reports(context, values)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("values", nargs="+", help="Titles to add, or task ids to cancel.")
    parser.add_argument("--cancel", action="store_true")
    args = parser.parse_args(argv)
    print(json.dumps(asyncio.run(_main(args.data_dir.resolve(), args.values, args.cancel))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
