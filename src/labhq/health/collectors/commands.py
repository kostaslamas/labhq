"""Probes as a read-only command plus a parser, run through a `CommandRunner` transport.

The same probe works on every host kind: the runner decides whether its command runs as a
local subprocess or over SSH. A probe that fails costs only its own metric.
"""

import asyncio
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from labhq.health.collector import Reading

logger = logging.getLogger(__name__)

type Argv = tuple[str, ...]


@dataclass(frozen=True)
class CommandResult:
    exit_status: int
    stdout: str
    stderr: str = ""


class CommandRunner(Protocol):
    async def run(self, argv: Argv) -> CommandResult: ...


class ProbeError(RuntimeError):
    """A command's output could not be read as its metric."""


@dataclass(frozen=True)
class ProbeContext:
    now: datetime
    # The previous sample of this host, or one interval ago: counters report what is new.
    since: datetime
    # Certificates to check on this host: `host:port` or a file path.
    certificates: tuple[str, ...] = ()


@dataclass(frozen=True)
class CommandProbe:
    name: str
    command: Callable[[ProbeContext], Argv | None]
    parse: Callable[[str, ProbeContext], list[Reading]]


async def run_probe(
    runner: CommandRunner, probe: CommandProbe, context: ProbeContext
) -> list[Reading]:
    argv = probe.command(context)
    if argv is None:
        # Nothing to ask this host, such as a certificate probe with no certificates.
        return []
    result = await runner.run(argv)
    if result.exit_status != 0:
        raise ProbeError(f"{argv[0]} exited with {result.exit_status}: {result.stderr.strip()}")
    return probe.parse(result.stdout, context)


async def run_probes(
    runner: CommandRunner, probes: Sequence[CommandProbe], context: ProbeContext
) -> list[Reading]:
    readings: list[Reading] = []
    for probe in probes:
        try:
            readings.extend(await run_probe(runner, probe, context))
        except (ProbeError, OSError, ValueError, TimeoutError) as error:
            # One failing probe must not cost the other metrics their sample.
            logger.warning("health probe %s failed: %s", probe.name, error)
    return readings


@dataclass(frozen=True)
class LocalRunner:
    """Runs a probe's command as a subprocess of the engine, never through a shell."""

    timeout_seconds: float = 60.0

    async def run(self, argv: Argv) -> CommandResult:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            async with asyncio.timeout(self.timeout_seconds):
                stdout, stderr = await process.communicate()
        finally:
            # A timeout or a cancelled loop must not leave the command running behind it.
            if process.returncode is None:
                process.kill()
                await process.wait()
        return CommandResult(
            exit_status=process.returncode if process.returncode is not None else -1,
            stdout=stdout.decode(errors="replace"),
            stderr=stderr.decode(errors="replace"),
        )
