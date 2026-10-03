"""An approved `host_intervention` runs exactly the approved command, as the intervention user.

Plan §10: "the fix needs biometrics". The voice line can never approve it (plan §5, rule 7);
the CLI confirmation stands in for the passkey until Phase 4 registers one.
"""

import getpass
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.approvals import ApprovalService, Executor, default_executors
from labhq.callcenter.actions.decide import decide
from labhq.callcenter.answers.refs import approval_ref
from labhq.clock import FakeClock
from labhq.db.enums import ApprovalStatus
from labhq.db.models import Approval, Comment, Host
from labhq.health.collectors import CommandResult
from labhq.health.intervention import (
    INTERVENTION_ACTION,
    HostIntervention,
    InterventionPayload,
    local_argv,
)
from labhq.health.ssh import SshTarget
from tests.db.factories import project_agent_task
from tests.health.stubs import StubRunner, StubSsh
from tests.health.world import add_remote_host, open_sessions

COMMAND = "systemctl restart nginx && systemctl is-active nginx"
RESTARTED = CommandResult(0, "active\n", "warning: unit file changed on disk\n")


@dataclass
class World:
    service: ApprovalService
    sessions: async_sessionmaker[AsyncSession]
    ssh: StubSsh
    local: StubRunner
    ticket: int


@pytest.fixture
async def world(database_url: str, clock: FakeClock) -> AsyncIterator[World]:
    ssh = StubSsh(StubRunner({"systemctl restart": RESTARTED}))
    local = StubRunner({"systemctl restart": RESTARTED})
    executor = HostIntervention(
        database_url=lambda: database_url, connect=ssh, local=lambda: local, clock=clock
    )
    executors = default_executors.copy()
    executors.register(
        INTERVENTION_ACTION,
        Executor(run=executor.run, validate=InterventionPayload.model_validate),
        replace=True,
    )
    async with open_sessions(database_url) as sessions:
        async with sessions() as db, db.begin():
            _, _, task = await project_agent_task(db, clock)
        service = ApprovalService(sessions, clock=clock, executors=executors)
        yield World(service, sessions, ssh, local, task.id)


def payload(world: World, host: str = "nas") -> dict[str, object]:
    return {"host": host, "command": COMMAND, "reason": "nginx failed", "ticket": world.ticket}


async def comments(world: World) -> list[str]:
    async with world.sessions() as db:
        return list(await db.scalars(select(Comment.body).where(Comment.task_id == world.ticket)))


async def test_an_intervention_runs_only_after_a_strong_approval_and_reports_on_the_ticket(
    world: World, clock: FakeClock
) -> None:
    await add_remote_host(world.sessions, clock, address="10.0.0.5:2222")
    approval = await world.service.request(INTERVENTION_ACTION, payload(world))
    assert approval.status == ApprovalStatus.PENDING
    assert world.ssh.logins == []

    async with world.sessions() as db:
        spoken = await decide(db, clock, approval_ref(approval.id), "approve")
    assert "passkey" in spoken
    assert (await world.service.get(approval.id)).status == ApprovalStatus.PENDING
    assert world.ssh.logins == []

    done = await world.service.approve(approval.id, decider="cli:owner", confirmation="cli")

    assert done.status == ApprovalStatus.EXECUTED
    assert world.ssh.logins == [(SshTarget("10.0.0.5", 2222), "labhq-fix")]
    assert world.ssh.runner.commands == [("sh", "-c", COMMAND)]
    assert done.execution is not None
    assert done.execution["exit_status"] == 0
    assert done.execution["user"] == "labhq-fix"
    assert done.execution["stdout"] == "active\n"
    [comment] = await comments(world)
    assert f"$ {COMMAND}" in comment
    assert "exited with 0" in comment
    assert "active" in comment and "unit file changed on disk" in comment


async def test_without_an_intervention_user_the_executor_refuses_and_runs_nothing(
    world: World, clock: FakeClock
) -> None:
    await add_remote_host(world.sessions, clock, address="10.0.0.5", intervention_user=None)
    approval = await world.service.request(INTERVENTION_ACTION, payload(world))

    done = await world.service.approve(approval.id, decider="cli:owner", confirmation="cli")

    assert done.status == ApprovalStatus.EXECUTION_FAILED
    assert done.execution is not None
    assert done.execution["error"] == "InterventionRefusedError"
    assert world.ssh.logins == []
    assert world.local.commands == []
    assert await comments(world) == []


async def test_a_local_intervention_runs_as_a_subprocess_of_the_engine(
    world: World, clock: FakeClock
) -> None:
    async with world.sessions() as db, db.begin():
        local = await db.scalar(select(Host).where(Host.name == "nas"))
        assert local is None
        now = clock.now()
        db.add(
            Host(
                name="labhq-box",
                is_local=True,
                intervention_user=getpass.getuser(),
                created_at=now,
                updated_at=now,
            )
        )
    approval = await world.service.request(INTERVENTION_ACTION, payload(world, "labhq-box"))

    done = await world.service.approve(approval.id, decider="cli:owner", confirmation="cli")

    assert done.status == ApprovalStatus.EXECUTED
    assert world.local.commands == [("sh", "-c", COMMAND)]
    assert world.ssh.logins == []
    assert len(await comments(world)) == 1


def test_another_local_user_is_reached_only_through_non_interactive_sudo() -> None:
    assert local_argv("id", getpass.getuser()) == ("sh", "-c", "id")
    assert local_argv("id", "labhq-fix-other") == (
        "sudo",
        "-n",
        "-u",
        "labhq-fix-other",
        "--",
        "sh",
        "-c",
        "id",
    )


@pytest.mark.parametrize("field", ["host", "command", "reason"])
async def test_a_request_without_a_host_command_or_reason_is_refused(
    world: World, field: str
) -> None:
    with pytest.raises(ValidationError):
        await world.service.request(INTERVENTION_ACTION, {**payload(world), field: "  "})
    async with world.sessions() as db:
        assert (await db.scalars(select(Approval))).all() == []


def test_the_engine_registers_the_executor_for_host_interventions() -> None:
    executor = default_executors.get(INTERVENTION_ACTION)
    assert executor.validate == InterventionPayload.model_validate
