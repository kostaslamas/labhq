"""Captured command output, and transports that answer probes with it instead of a machine."""

from collections.abc import AsyncIterator, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from labhq.health.collectors import CommandResult, CommandRunner
from labhq.health.collectors.commands import Argv
from labhq.health.ssh import SshTarget

FIXTURES = Path(__file__).parent / "fixtures"
NOT_FOUND = CommandResult(127, "", "command not found")

# A fragment of the command line -> the fixture with what that command printed on a machine.
CAPTURED: dict[str, str] = {
    "systemctl list-units": "systemctl_list_units.txt",
    "docker ps": "docker_ps.txt",
    "smartctl --scan": "smartctl.txt",
    "journalctl": "journalctl.json",
    "openssl": "openssl_enddate.txt",
    "apt list": "apt_upgradable.txt",
    "/proc/stat": "proc_stat.txt",
    "/proc/meminfo": "proc_meminfo.txt",
    "/proc/loadavg": "proc_loadavg.txt",
    "df -P": "df.txt",
}


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


def captured(overrides: Mapping[str, CommandResult] | None = None) -> dict[str, CommandResult]:
    """Every probe answered from its fixture, with `overrides` replacing some answers."""
    answers = {fragment: CommandResult(0, fixture(name)) for fragment, name in CAPTURED.items()}
    answers.update(overrides or {})
    return answers


def answer(answers: Mapping[str, CommandResult], command_line: str) -> CommandResult:
    for fragment, result in answers.items():
        if fragment in command_line:
            return result
    return NOT_FOUND


@dataclass
class StubRunner:
    """A `CommandRunner` that records each command and answers from `answers`."""

    answers: Mapping[str, CommandResult] = field(default_factory=captured)
    commands: list[Argv] = field(default_factory=list)

    async def run(self, argv: Argv) -> CommandResult:
        self.commands.append(argv)
        return answer(self.answers, " ".join(argv))


@dataclass
class StubSsh:
    """A stubbed SSH transport: records who connected where, and runs nothing real."""

    runner: StubRunner = field(default_factory=StubRunner)
    logins: list[tuple[SshTarget, str]] = field(default_factory=list)

    def __call__(self, target: SshTarget, user: str) -> AbstractAsyncContextManager[CommandRunner]:
        @asynccontextmanager
        async def session() -> AsyncIterator[CommandRunner]:
            self.logins.append((target, user))
            yield self.runner

        return session()
