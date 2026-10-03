"""Rows for answer tests: a small busy database and a bulk-seeded large one."""

from datetime import timedelta

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.clock import FakeClock
from labhq.db.enums import ApprovalStatus, HostStatus, RiskClass, RunStatus
from labhq.db.models import (
    Agent,
    AgentQuestion,
    Approval,
    CostEvent,
    HealthRule,
    HealthSample,
    Host,
    Incident,
    Project,
    Run,
    Task,
)
from tests.db.factories import project_agent_task

Base3 = tuple[Project, Agent, Task]


async def seed_busy(
    session: AsyncSession, clock: FakeClock, base: Base3 | None = None
) -> dict[str, int]:
    """One of everything the answers read, all inside the last few hours."""
    now = clock.now()
    project, agent, task = base or await project_agent_task(session, clock)
    task.title = "Ship the | login {page}"
    session.add(
        Run(
            agent_id=agent.id,
            task_id=task.id,
            adapter="fake",
            status=RunStatus.SUCCEEDED,
            created_at=now - timedelta(hours=2),
            finished_at=now - timedelta(hours=1),
        )
    )
    session.add(
        Approval(
            type="push",
            risk_class=RiskClass.LIGHT,
            status=ApprovalStatus.EXECUTED,
            task_id=task.id,
            decided_at=now - timedelta(minutes=30),
            created_at=now - timedelta(hours=1),
        )
    )
    pending = Approval(
        type="merge_branch",
        risk_class=RiskClass.HEAVY,
        task_id=task.id,
        created_at=now - timedelta(minutes=10),
    )
    question = AgentQuestion(
        agent_id=agent.id,
        task_id=task.id,
        question="Which branch should I release from?",
        fingerprint="b" * 64,
        created_at=now - timedelta(minutes=5),
    )
    session.add_all([pending, question])
    session.add(
        CostEvent(
            agent_id=agent.id,
            project_id=project.id,
            cost_micros=1_230_000,
            created_at=now - timedelta(minutes=20),
        )
    )
    host = Host(name="build-box", status=HostStatus.DEGRADED, created_at=now, updated_at=now)
    session.add(host)
    await session.flush()
    rule = HealthRule(
        type="threshold",
        name="Disk almost full",
        params={"metric": "disk.percent", "comparison": "gt", "value": 90},
        reason="test",
        created_by="test",
        created_at=now,
        updated_at=now,
    )
    session.add(rule)
    await session.flush()
    session.add(Incident(rule_id=rule.id, host_id=host.id, opened_at=now - timedelta(hours=3)))
    for offset, value in ((20, 80.0), (10, 93.4)):
        session.add(
            HealthSample(
                host_id=host.id,
                metric="disk.percent",
                subject="/",
                value=value,
                sampled_at=now - timedelta(minutes=offset),
            )
        )
    await session.commit()
    return {"approval": pending.id, "question": question.id}


async def seed_runs(session: AsyncSession, clock: FakeClock, count: int) -> Base3:
    """Bulk-insert `count` runs, two thirds of them succeeded, spread over the last hours."""
    now = clock.now()
    base = await project_agent_task(session, clock)
    _, agent, task = base
    rows = [
        {
            "agent_id": agent.id,
            "task_id": task.id,
            "adapter": "fake",
            "status": RunStatus.SUCCEEDED if n % 3 else RunStatus.FAILED,
            "created_at": now - timedelta(seconds=n),
            "finished_at": now - timedelta(seconds=n // 2),
        }
        for n in range(count)
    ]
    await session.execute(insert(Run), rows)
    await session.commit()
    return base
