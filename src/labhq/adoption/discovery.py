"""Find running CLI agents: process command lines and working directories, nothing else.

Discovery reads the process table only (through psutil: the command line, start time and
working directory of each process). It never opens an agent's session store, logs or
credential files (ADR 0001), and it never reads a process's environment, which can hold
tokens.
"""

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

import psutil

from labhq.adapters.tmux import AgentKind, AgentKinds

# A CLI runs as its own binary (`claude`) or under an interpreter (`node .../gemini`,
# `python .../aider`), so the program name is one of the first two words.
PROGRAM_WORDS = 2


@dataclass(frozen=True)
class RunningAgent:
    pid: int
    kind: str
    cwd: Path
    # The process's start time: with the pid it names one process, even after pid reuse.
    started_at: float
    command: tuple[str, ...]


Processes = Callable[[], Iterable[psutil.Process]]


def all_processes() -> Iterable[psutil.Process]:
    return psutil.process_iter(["pid", "cmdline", "create_time"])


def adoptable(kinds: AgentKinds) -> dict[str, AgentKind]:
    """Process name to agent kind, for every kind that can continue a conversation."""
    names: dict[str, AgentKind] = {}
    for name in kinds.names():
        kind = kinds.get(name)
        if kind.continue_ is not None:
            names.update(dict.fromkeys(kind.process_names, kind))
    return names


def kind_of(command: Iterable[str], names: dict[str, AgentKind]) -> AgentKind | None:
    for word in list(command)[:PROGRAM_WORDS]:
        kind = names.get(Path(word).name)
        if kind is not None:
            return kind
    return None


def discover(kinds: AgentKinds, processes: Processes = all_processes) -> list[RunningAgent]:
    """Running processes of the known CLIs, with their working directories."""
    return sorted(_running(kinds, processes), key=lambda agent: agent.pid)


def find_running(pid: int, kinds: AgentKinds, processes: Processes = all_processes) -> RunningAgent:
    for agent in discover(kinds, processes):
        if agent.pid == pid:
            return agent
    raise LookupError(f"process {pid} is not a running agent of a known CLI")


def _running(kinds: AgentKinds, processes: Processes) -> Iterator[RunningAgent]:
    names = adoptable(kinds)
    own = psutil.Process().pid
    for process in processes():
        info = getattr(process, "info", None) or {}
        command = tuple(info.get("cmdline") or ())
        kind = kind_of(command, names)
        if kind is None or process.pid == own:
            continue
        try:
            cwd = Path(process.cwd())
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
        yield RunningAgent(process.pid, kind.name, cwd, float(info["create_time"]), command)


def is_alive(pid: int, started_at: float) -> bool:
    """Whether the process `pid`, started at `started_at`, still runs."""
    try:
        process = psutil.Process(pid)
        return process.create_time() == started_at and process.status() != psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, psutil.ZombieProcess):
        return False
