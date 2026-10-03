"""A graphify index per project, so managers and workers query code structure instead of
reading files (plan §7.1). Like the `rtk` hook it is optional and must earn its place: the
A/B in `docs/checks/graphify-ab.md` decides whether agents keep it on.

graphify (PyPI `graphifyy`, command `graphify`; https://github.com/safishamsi/graphify,
checked against 0.9.74 on 2026-10-03 with `graphify --help` and a real build):

- `graphify extract <path> --code-only --out <dir>` parses code locally with tree-sitter and
  calls no model ("index code (local AST, no API key)"). It writes `<dir>/graphify-out/`:
  `graph.json`, `manifest.json`, `.graphify_analysis.json` and an AST `cache/` that makes the
  next build incremental. Measured: with `--out` outside the repository nothing is written
  inside it, so no `.git/info/exclude` entry is needed. Without `--code-only` the same command
  sends docs to an LLM backend, and `cluster-only`/`label` name communities with one; labhq
  runs neither.
- `graphify query "<question>" --graph <graph.json> [--budget N]`, `graphify explain "<X>"`
  and `graphify path "<A>" "<B>"` read the graph and print a token-capped answer.
- MCP: `python -m graphify.serve <graph.json>` serves `query_graph`, `get_node`,
  `get_neighbors`, `shortest_path` and more over stdio. The run options of #70 serve only
  labhq's own in-process tools (`strict_mcp_config`), so agents get the query commands in a
  system prompt section instead.

`agents.config["graphify"] = true` switches the section on per agent, so the A/B runs the same
task with and without it. A missing binary is reported once and turns the measure off; it
never fails a run or a loop.
"""

import asyncio
import json
import logging
import os
import shlex
import shutil
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.clock import Clock
from labhq.db.enums import ProjectStatus
from labhq.db.models import Agent, Project, Task
from labhq.settings import Settings

logger = logging.getLogger(__name__)

GRAPHIFY_BINARY = "graphify"
# `agents.config` key of the per-agent switch.
CONFIG_KEY = "graphify"
GRAPHIFY_MISSING = "graphify_missing"
# Under `<data_dir>`; one directory per project id, never inside the owner's repository.
INDEX_DIR = "graphify"
# graphify always writes into this directory below `--out`.
OUTPUT_SUBDIR = "graphify-out"
GRAPH_FILE = "graph.json"
# labhq's own record of the last build, next to graphify's output.
STAMP_FILE = "labhq-build.json"
# The prompt section: after the role (100), before the output style (200).
GRAPHIFY_SECTION = "graphify"
GRAPHIFY_POSITION = 150
# graphify reads nothing else from the environment for a code-only build. Keeping API keys out
# means even a future default that called a backend would find none.
_CHILD_ENV_KEYS = ("PATH", "HOME")


class GraphifySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LABHQ_GRAPHIFY_", extra="ignore")

    # An index older than this is rebuilt even when HEAD has not moved (uncommitted work).
    refresh_seconds: float = Field(default=3600.0, gt=0)
    build_timeout_seconds: float = Field(default=600.0, gt=0)
    # graphify's own default; caps what one query adds to the agent's context.
    query_budget_tokens: int = Field(default=2000, gt=0)


def is_enabled(config: Mapping[str, Any]) -> bool:
    return config.get(CONFIG_KEY) is True


def _child_env() -> dict[str, str]:
    return {key: os.environ[key] for key in _CHILD_ENV_KEYS if key in os.environ}


async def _run(argv: list[str], cwd: Path, timeout: float) -> tuple[int, str] | None:
    """Exit code and combined output, or None when the program could not start or hung."""
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=_child_env(),
        )
    except OSError:
        logger.warning("%s could not start", argv[0], exc_info=True)
        return None
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        logger.warning("%s timed out after %ss", argv[0], timeout)
        return None
    return process.returncode or 0, stdout.decode("utf-8", errors="replace")


async def repo_head(repo: Path) -> str | None:
    if not repo.is_dir():
        return None
    result = await _run(["git", "-C", str(repo), "rev-parse", "HEAD"], repo, 30.0)
    if result is None or result[0] != 0:
        return None
    return result[1].strip() or None


class GraphifyIndex:
    """Builds, refreshes and points agents at the per-project graphify index."""

    def __init__(
        self,
        data_dir: Path,
        settings: GraphifySettings | None = None,
        *,
        search_path: str | None = None,
    ) -> None:
        self._root = data_dir / INDEX_DIR
        self._settings = settings if settings is not None else GraphifySettings()
        self._search_path = search_path
        self._missing_reported = False

    def binary(self) -> Path | None:
        """The graphify on the search path. Looked up each time, so installing it turns it on."""
        found = shutil.which(GRAPHIFY_BINARY, path=self._search_path)
        if found is not None:
            self._missing_reported = False
            return Path(found)
        if not self._missing_reported:
            self._missing_reported = True
            logger.warning(
                "%s: graphify is not on PATH; agents read files instead of the code graph. "
                "Install graphifyy to enable the index.",
                GRAPHIFY_MISSING,
            )
        return None

    def output_dir(self, project_id: int) -> Path:
        return self._root / str(project_id)

    def graph_path(self, project_id: int) -> Path:
        return self.output_dir(project_id) / OUTPUT_SUBDIR / GRAPH_FILE

    def _stamp_path(self, project_id: int) -> Path:
        return self.output_dir(project_id) / STAMP_FILE

    async def build(self, project: Project, now: datetime) -> bool:
        """Build or update `project`'s index; False when graphify is missing or failed."""
        binary = self.binary()
        if binary is None:
            return False
        out = self.output_dir(project.id)
        out.mkdir(parents=True, exist_ok=True)
        repo = Path(project.repo_path)
        argv = [str(binary), "extract", str(repo), "--code-only", "--out", str(out)]
        # The working directory is the index's own, so a relative write lands there too.
        result = await _run(argv, out, self._settings.build_timeout_seconds)
        if result is None or result[0] != 0:
            detail = result[1][-500:] if result is not None else ""
            logger.warning("graphify build of project %s failed: %s", project.id, detail)
            return False
        stamp = {"built_at": now.isoformat(), "head": await repo_head(repo)}
        self._stamp_path(project.id).write_text(json.dumps(stamp), encoding="utf-8")
        return True

    def _due(self, project: Project, head: str | None, now: datetime) -> bool:
        stamp_path = self._stamp_path(project.id)
        if not self.graph_path(project.id).exists() or not stamp_path.exists():
            return True
        try:
            stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
            built_at = datetime.fromisoformat(stamp["built_at"])
        except (ValueError, KeyError, TypeError):
            return True
        # A moved HEAD is a merge (approved or not) or a pull: the graph is stale now.
        if stamp.get("head") != head:
            return True
        return (now - built_at).total_seconds() >= self._settings.refresh_seconds

    async def refresh(self, sessions: async_sessionmaker[AsyncSession], clock: Clock) -> int:
        """Build every active project whose index is missing, stale or behind HEAD."""
        if self.binary() is None:
            return 0
        async with sessions() as db:
            projects = list(
                await db.scalars(select(Project).where(Project.status == ProjectStatus.ACTIVE))
            )
        built = 0
        for project in projects:
            head = await repo_head(Path(project.repo_path))
            if self._due(project, head, clock.now()) and await self.build(project, clock.now()):
                built += 1
        return built

    def section(self, agent: Agent, task: Task | None) -> str | None:
        """The query instruction for an agent with the switch on and an index to query."""
        if not is_enabled(agent.config):
            return None
        project_id = task.project_id if task is not None else agent.project_id
        if project_id is None:
            return None
        binary = self.binary()
        graph = self.graph_path(project_id)
        if binary is None or not graph.exists():
            return None
        return query_instruction(binary, graph, self._settings.query_budget_tokens)


def query_instruction(binary: Path, graph: Path, budget: int) -> str:
    command = shlex.quote(str(binary))
    target = f"--graph {shlex.quote(str(graph))}"
    return (
        "## Code graph\n"
        "This project has a graphify index of its code: files, classes, functions and how "
        "they connect. Before reading source files to find where something lives or how "
        "parts connect, query the index with Bash:\n"
        f'- `{command} query "<question>" {target} --budget {budget}`\n'
        f'- `{command} explain "<symbol>" {target}`\n'
        f'- `{command} path "<symbol A>" "<symbol B>" {target}`\n'
        "Open a file only when the graph does not answer, or to read or change the lines "
        "it points to. The index can lag uncommitted edits."
    )


@lru_cache(maxsize=4)
def index_for(data_dir: Path) -> GraphifyIndex:
    """One index per data directory, so the prompt section and the loop report once together."""
    return GraphifyIndex(data_dir)


def default_section(agent: Agent, task: Task | None) -> str | None:
    if not is_enabled(agent.config):
        return None
    return index_for(Settings().data_dir).section(agent, task)


class _LoopContext(Protocol):
    @property
    def settings(self) -> Settings: ...

    @property
    def sessions(self) -> async_sessionmaker[AsyncSession]: ...

    @property
    def clock(self) -> Clock: ...


class _LoopServices(Protocol):
    @property
    def context(self) -> _LoopContext: ...


def refresh_loop(services: _LoopServices) -> Callable[[], Awaitable[int]]:
    """The always-on program's step: new projects get an index, stale ones a rebuild."""
    context = services.context
    index = index_for(context.settings.data_dir)

    async def step() -> int:
        return await index.refresh(context.sessions, context.clock)

    return step
