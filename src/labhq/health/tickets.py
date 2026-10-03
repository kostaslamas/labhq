"""Incidents of `ticket` rules become tasks in the infra project, with a diagnosis.

The infra project is reserved and created on first need; its `repo_path` is a directory under
the data directory, since it holds no code of its own. One incident opens one task; recovery
comments on it. Closing the task stays with the IT agent or the owner.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.clock import Clock
from labhq.db.models import Comment, HealthRule, HealthSample, Host, Incident, Project, Task
from labhq.settings import Settings

INFRA_PROJECT = "infra"
INFRA_DIRECTORY = "infra"
RECENT_SAMPLES = 10


def default_data_dir() -> Path:
    # Read per call, not cached: one process may serve several configurations (tests).
    return Settings().data_dir


async def infra_project(db: AsyncSession, clock: Clock, data_dir: Path) -> Project:
    project = await db.scalar(select(Project).where(Project.name == INFRA_PROJECT))
    if project is not None:
        return project
    directory = data_dir / INFRA_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)
    now = clock.now()
    project = Project(name=INFRA_PROJECT, repo_path=str(directory), created_at=now, updated_at=now)
    db.add(project)
    await db.flush()
    return project


async def _recent_samples(
    db: AsyncSession, host: Host, metric: str, until: datetime
) -> list[HealthSample]:
    rows = await db.scalars(
        select(HealthSample)
        .where(
            HealthSample.host_id == host.id,
            HealthSample.metric == metric,
            HealthSample.sampled_at <= until,
        )
        .order_by(HealthSample.sampled_at.desc(), HealthSample.id.desc())
        .limit(RECENT_SAMPLES)
    )
    return list(reversed(rows.all()))


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


async def diagnosis(db: AsyncSession, rule: HealthRule, host: Host, incident: Incident) -> str:
    """What the IT agent or the owner needs to start: no query of their own required."""
    lines = [
        f"Host: {host.name} (id {host.id})",
        f"Rule: {rule.id} {rule.name!r}, type {rule.type}, action {rule.action}",
        f"Params: {_json(rule.params)}",
        f"Reason: {rule.reason}",
        f"Began: {incident.opened_at.isoformat()}",
        f"Observed: {_json(incident.details)}",
    ]
    metric = incident.details.get("metric")
    if isinstance(metric, str):
        samples = await _recent_samples(db, host, metric, incident.opened_at)
        lines.append(f"Recent samples of {metric}:")
        lines.extend(
            f"- {sample.sampled_at.isoformat()} {sample.subject or '-'} {sample.value}"
            for sample in samples
        )
    return "\n".join(lines)


async def open_ticket(
    db: AsyncSession,
    clock: Clock,
    rule: HealthRule,
    host: Host,
    incident: Incident,
    data_dir: Path | None = None,
) -> Task:
    """Create the incident's task once and link it from `incidents.task_id`."""
    if incident.task_id is not None:
        existing = await db.get(Task, incident.task_id)
        if existing is not None:
            return existing
    project = await infra_project(db, clock, data_dir or default_data_dir())
    now = clock.now()
    task = Task(
        project_id=project.id,
        title=f"{host.name}: {rule.name}"[:300],
        description=await diagnosis(db, rule, host, incident),
        created_at=now,
        updated_at=now,
    )
    db.add(task)
    await db.flush()
    incident.task_id = task.id
    await db.flush()
    return task


async def comment_recovery(
    db: AsyncSession, clock: Clock, rule: HealthRule, host: Host, incident: Incident
) -> Comment | None:
    if incident.task_id is None:
        return None
    resolved = incident.resolved_at or clock.now()
    comment = Comment(
        task_id=incident.task_id,
        body=(
            f"Recovered at {resolved.isoformat()}: rule {rule.id} {rule.name!r} no longer "
            f"holds on {host.name}. The incident is resolved; the task stays open for review."
        ),
        created_at=clock.now(),
    )
    db.add(comment)
    await db.flush()
    return comment
