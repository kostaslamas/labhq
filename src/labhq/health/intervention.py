"""The `host_intervention` executor: an approved fix runs on a machine, executed by the engine.

Agents only request (plan §5). Once a human with a strong enough confirmation approves, the
engine runs exactly the approved command on the named host: locally as a subprocess, on a
remote host over SSH as the host's `intervention_user`, never as the read-only collection
user. A host without an intervention user is refused and nothing runs. The output and exit
status go back on the approval and as a comment on the ticket the request named.

The approvals service runs executors in a worker thread, so this one opens its own event
loop and its own database engine there.
"""

import asyncio
import getpass
from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from labhq.clock import Clock, SystemClock
from labhq.db import create_engine, session_factory
from labhq.db.models import Comment, Host, Task
from labhq.health.collectors import CommandResult, CommandRunner, LocalRunner
from labhq.health.collectors.commands import Argv
from labhq.health.collectors.remote import Connect
from labhq.health.ssh import SshSettings, SshTarget, ssh_runner
from labhq.settings import Settings

INTERVENTION_ACTION = "host_intervention"
# Kept from the end: the last lines of a long command are the ones that explain it.
MAX_OUTPUT_CHARS = 20_000


class InterventionPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    host: str = Field(min_length=1)
    # Run by the host's `sh -c` exactly as approved; the operator reads this string.
    command: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    # The task that tracks the problem; the result is commented there.
    ticket: int = Field(gt=0)

    @field_validator("host", "command", "reason")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class InterventionRefusedError(RuntimeError):
    """The engine will not run this intervention; nothing was executed."""


def shell(command: str) -> Argv:
    return ("sh", "-c", command)


def local_argv(command: str, user: str) -> Argv:
    # The engine's own user runs it directly; another user only through non-interactive sudo.
    if user == getpass.getuser():
        return shell(command)
    return ("sudo", "-n", "-u", user, "--", *shell(command))


def _intervention_connect() -> Connect:
    def connect(target: SshTarget, user: str) -> AbstractAsyncContextManager[CommandRunner]:
        settings = SshSettings()
        return ssh_runner(
            target, user, settings, timeout_seconds=settings.intervention_timeout_seconds
        )

    return connect


def _tail(text: str) -> str:
    return text if len(text) <= MAX_OUTPUT_CHARS else text[-MAX_OUTPUT_CHARS:]


def _comment(request: InterventionPayload, user: str, result: CommandResult) -> str:
    return "\n".join(
        [
            f"Approved intervention on {request.host} as {user} exited with {result.exit_status}.",
            f"Reason: {request.reason}",
            "",
            "```",
            f"$ {request.command}",
            "```",
            "stdout:",
            "```",
            _tail(result.stdout).rstrip(),
            "```",
            "stderr:",
            "```",
            _tail(result.stderr).rstrip(),
            "```",
        ]
    )


@dataclass(frozen=True)
class HostIntervention:
    database_url: Callable[[], str] = lambda: Settings().resolved_database_url
    connect: Connect = field(default_factory=_intervention_connect)
    local: Callable[[], CommandRunner] = lambda: LocalRunner(
        SshSettings().intervention_timeout_seconds
    )
    clock: Clock = field(default_factory=SystemClock)

    def run(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return asyncio.run(self.execute(payload))

    async def _run_on(self, host: Host, user: str, command: str) -> CommandResult:
        if host.is_local:
            return await self.local().run(local_argv(command, user))
        if not host.address:
            raise InterventionRefusedError(f"host {host.name} has no address")
        async with self.connect(SshTarget.parse(host.address), user) as runner:
            return await runner.run(shell(command))

    async def execute(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        request = InterventionPayload.model_validate(payload)
        engine = create_engine(self.database_url())
        sessions = session_factory(engine)
        try:
            async with sessions() as db:
                host = await db.scalar(select(Host).where(Host.name == request.host))
                ticket = await db.get(Task, request.ticket)
            if host is None:
                raise InterventionRefusedError(f"no host named {request.host}")
            if ticket is None:
                raise InterventionRefusedError(f"no ticket {request.ticket}")
            user = host.intervention_user
            if not user:
                raise InterventionRefusedError(
                    f"host {host.name} has no intervention user; nothing was run"
                )
            result = await self._run_on(host, user, request.command)
            async with sessions() as db, db.begin():
                db.add(
                    Comment(
                        task_id=ticket.id,
                        body=_comment(request, user, result),
                        created_at=self.clock.now(),
                    )
                )
        finally:
            await engine.dispose()
        return {
            "host": host.name,
            "user": user,
            "command": request.command,
            "exit_status": result.exit_status,
            "stdout": _tail(result.stdout),
            "stderr": _tail(result.stderr),
            "ticket": ticket.id,
        }
