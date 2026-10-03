"""Memory that managers and leads carry from one run to the next (plan §2).

The canonical copy lives in the agent's home directory, `<data_dir>/agents/<agent_id>/`.
Before a run the engine copies it to `.labhq/memory.md` in the run's working directory and
reads it into the prompt; after the run it takes the file back if the agent changed it.
A file and a prompt preamble work with every adapter and need no session resume, so a
fresh session, another task or another worktree sees the same memory. `.labhq/` is in
`.git/info/exclude` (ADR 0004), so memory never reaches a commit.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from labhq.db.models import Agent
from labhq.memory.preamble import memory_preamble
from labhq.memory.settings import MemorySettings, get_memory_settings
from labhq.settings import Settings

MEMORY_RELATIVE_PATH = Path(".labhq") / "memory.md"
# Overrides the role default in `agents.config`: true keeps memory, false never does.
MEMORY_CONFIG_KEY = "memory"
CANONICAL_NAME = "memory.md"
# Holds how many lines the last store dropped; absent when nothing was dropped.
DROPPED_NAME = "memory.dropped"


@dataclass(frozen=True)
class PreparedMemory:
    """Memory copied into a run's working directory, and what the run's prompt says of it."""

    agent_id: int
    cwd: Path
    seeded: str
    preamble: str

    @property
    def path(self) -> Path:
        return self.cwd / MEMORY_RELATIVE_PATH

    def prompt(self, prompt: str) -> str:
        return f"{self.preamble}\n\n{prompt}"


@dataclass(frozen=True)
class MemoryUpdate:
    """A changed memory file, stored as the canonical copy after a run."""

    chars: int
    dropped_lines: int

    def as_event_payload(self) -> dict[str, Any]:
        return {"chars": self.chars, "dropped_lines": self.dropped_lines}


def truncate_oldest(text: str, limit: int) -> tuple[str, int]:
    """Keep the newest lines that fit in `limit` characters; return them and how many went.

    A single newest line longer than the limit keeps its tail, so memory is never empty
    just because the agent wrote one long line.
    """
    if len(text) <= limit:
        return text, 0
    lines = text.splitlines(keepends=True)
    kept: list[str] = []
    size = 0
    for line in reversed(lines):
        if size + len(line) > limit:
            break
        kept.append(line)
        size += len(line)
    if not kept:
        return text[-limit:], len(lines) - 1
    return "".join(reversed(kept)), len(lines) - len(kept)


class AgentMemory:
    """Home directories and canonical memory of long-lived agents, under one root."""

    def __init__(self, root: Path, settings: MemorySettings | None = None) -> None:
        self._root = root
        self._settings = settings if settings is not None else get_memory_settings()

    @classmethod
    def from_settings(cls, settings: Settings) -> "AgentMemory":
        return cls(settings.data_dir / "agents")

    def keeps_memory(self, agent: Agent) -> bool:
        override = agent.config.get(MEMORY_CONFIG_KEY)
        if override is not None:
            return bool(override)
        return agent.role in self._settings.memory_roles

    def home(self, agent_id: int) -> Path:
        return self._root / str(agent_id)

    def read(self, agent_id: int) -> str:
        canonical = self.home(agent_id) / CANONICAL_NAME
        return canonical.read_text(encoding="utf-8") if canonical.exists() else ""

    def prepare(self, agent: Agent, cwd: Path | None) -> PreparedMemory | None:
        """Seed `.labhq/memory.md` for a run; None for an agent without memory.

        A run with no working directory of its own works in the agent's home.
        """
        if not self.keeps_memory(agent):
            return None
        home = self.home(agent.id)
        home.mkdir(parents=True, exist_ok=True)
        cwd = cwd if cwd is not None else home
        seeded = self.read(agent.id)
        prepared = PreparedMemory(
            agent_id=agent.id,
            cwd=cwd,
            seeded=seeded,
            preamble=memory_preamble(seeded, self._dropped(agent.id), self._settings),
        )
        prepared.path.parent.mkdir(parents=True, exist_ok=True)
        prepared.path.write_text(seeded, encoding="utf-8")
        return prepared

    def collect(self, prepared: PreparedMemory) -> MemoryUpdate | None:
        """Store the run's memory file if the agent changed it; None when it did not."""
        if not prepared.path.exists():
            return None
        text = prepared.path.read_text(encoding="utf-8")
        if text == prepared.seeded:
            return None
        kept, dropped = truncate_oldest(text, self._settings.memory_max_chars)
        home = self.home(prepared.agent_id)
        (home / CANONICAL_NAME).write_text(kept, encoding="utf-8")
        marker = home / DROPPED_NAME
        if dropped:
            marker.write_text(str(dropped), encoding="utf-8")
        else:
            marker.unlink(missing_ok=True)
        return MemoryUpdate(chars=len(kept), dropped_lines=dropped)

    def _dropped(self, agent_id: int) -> int:
        marker = self.home(agent_id) / DROPPED_NAME
        return int(marker.read_text(encoding="utf-8")) if marker.exists() else 0
