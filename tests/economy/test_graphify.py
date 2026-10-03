"""The graphify index: built outside the repository, offered per agent, off when missing."""

import asyncio
import json
import logging
import stat
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.adapters import FakeAdapter, FakeScript, default_registry
from labhq.clock import FakeClock
from labhq.db import create_engine, session_factory
from labhq.db.enums import RunStatus
from labhq.db.models import Agent, Project
from labhq.economy.graphify import (
    GRAPHIFY_MISSING,
    GRAPHIFY_POSITION,
    GRAPHIFY_SECTION,
    GraphifyIndex,
    GraphifySettings,
    default_section,
)
from labhq.memory import AgentMemory
from labhq.program import default_loops, run_loop
from labhq.prompts import PromptRegistry, RoleRegistry, builtin_registry
from labhq.runs import RunService
from labhq.worktrees.git import run_git
from tests.db.factories import project_agent_task
from tests.program.conftest import Passes, SteppedClock
from tests.worktrees.conftest import isolated_git, remote, repo
from tests.worktrees.gitrepo import commit_file

__all__ = ["isolated_git", "remote", "repo"]

# Stands in for `graphify extract <path> --code-only --out <dir>`: records its working
# directory and arguments next to itself (the child gets no other environment), then writes
# the graph where graphify does.
STUB_GRAPHIFY = """#!/bin/sh
log="$(dirname "$0")/calls.log"
printf '%s\\n' "$PWD" "$@" >> "$log"
printf -- '--\\n' >> "$log"
[ "$1" = extract ] || exit 2
mkdir -p "$5/graphify-out"
printf '{"nodes": [], "links": []}\\n' > "$5/graphify-out/graph.json"
"""


def install_stub(directory: Path, script: str = STUB_GRAPHIFY) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    binary = directory / "graphify"
    binary.write_text(script, encoding="utf-8")
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return binary


def calls(binary: Path) -> list[list[str]]:
    log = binary.parent / "calls.log"
    if not log.exists():
        return []
    blocks = log.read_text(encoding="utf-8").split("--\n")
    return [block.splitlines() for block in blocks if block]


@pytest.fixture
def stub(tmp_path: Path) -> Path:
    return install_stub(tmp_path / "bin")


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
async def sessions(database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(database_url)
    try:
        yield session_factory(engine)
    finally:
        await engine.dispose()


def index_with(data_dir: Path, search_path: Path, refresh_seconds: float = 3600) -> GraphifyIndex:
    settings = GraphifySettings(refresh_seconds=refresh_seconds)
    return GraphifyIndex(data_dir, settings, search_path=str(search_path))


@pytest.mark.posix_only("the graphify stub is a POSIX shell script")
async def test_a_build_writes_under_the_data_directory_and_never_into_the_repository(
    repo: Path, stub: Path, data_dir: Path, clock: FakeClock
) -> None:
    index = index_with(data_dir, stub.parent)
    project = Project(id=7, name="demo", repo_path=str(repo))

    assert await index.build(project, clock.now())

    out = data_dir / "graphify" / "7"
    (call,) = calls(stub)
    assert call == [str(out), "extract", str(repo), "--code-only", "--out", str(out)]
    assert index.graph_path(7) == out / "graphify-out" / "graph.json"
    assert index.graph_path(7).exists()
    stamp = json.loads((out / "labhq-build.json").read_text(encoding="utf-8"))
    assert stamp["head"] == run_git("rev-parse", "HEAD", cwd=repo).strip()
    # Not even an ignored file: graphify's output never lands in the owner's checkout.
    assert run_git("status", "--porcelain", "--ignored", cwd=repo) == ""


async def test_a_failed_build_reports_false_and_leaves_no_stamp(
    repo: Path, tmp_path: Path, data_dir: Path, clock: FakeClock
) -> None:
    failing = install_stub(tmp_path / "failing", "#!/bin/sh\necho boom\nexit 1\n")
    index = index_with(data_dir, failing.parent)

    assert not await index.build(Project(id=3, name="x", repo_path=str(repo)), clock.now())
    assert not (data_dir / "graphify" / "3" / "labhq-build.json").exists()


async def manager(
    sessions: async_sessionmaker[AsyncSession], clock: FakeClock, config: dict[str, object]
) -> tuple[int, int]:
    async with sessions() as db:
        _, agent, task = await project_agent_task(db, clock)
        await db.execute(
            update(Agent).where(Agent.id == agent.id).values(role="manager", config=config)
        )
        await db.commit()
        return agent.id, task.id


async def run_and_record(
    sessions: async_sessionmaker[AsyncSession],
    clock: FakeClock,
    tmp_path: Path,
    prompts: PromptRegistry,
    ids: tuple[int, int],
) -> tuple[FakeScript, RunStatus]:
    script = FakeScript()
    adapters = default_registry.copy()
    adapters.register("fake", lambda: FakeAdapter(script), replace=True)
    agent_id, task_id = ids
    service = RunService(
        sessions,
        clock=clock,
        registry=adapters,
        memory=AgentMemory(tmp_path / "agents"),
        prompts=prompts,
    )
    run = await service.execute(agent_id=agent_id, task_id=task_id, prompt="where is auth?")
    return script, run.status


def prompts_with(index: GraphifyIndex) -> PromptRegistry:
    roles = RoleRegistry()
    roles.register("manager", "You are the project's manager.")
    registry = builtin_registry(roles)
    registry.register(GRAPHIFY_SECTION, index.section, position=GRAPHIFY_POSITION, replace=True)
    return registry


def built_graph(index: GraphifyIndex, project_id: int) -> Path:
    graph = index.graph_path(project_id)
    graph.parent.mkdir(parents=True)
    graph.write_text("{}", encoding="utf-8")
    return graph


@pytest.mark.parametrize(
    "switch",
    [
        pytest.param(
            True, marks=pytest.mark.posix_only("the graphify stub is a POSIX shell script")
        ),
        False,
    ],
)
async def test_the_switch_decides_whether_a_manager_gets_the_query_instruction(
    sessions: async_sessionmaker[AsyncSession],
    clock: FakeClock,
    tmp_path: Path,
    stub: Path,
    data_dir: Path,
    switch: bool,
) -> None:
    index = index_with(data_dir, stub.parent)
    # The factory's project is the first row of a fresh database.
    graph = built_graph(index, 1)

    ids = await manager(sessions, clock, {"graphify": switch})
    script, status = await run_and_record(sessions, clock, tmp_path, prompts_with(index), ids)

    (request,) = script.requests
    append = request.system_prompt_append or ""
    assert status is RunStatus.SUCCEEDED
    assert append.startswith("You are the project's manager.")
    # graphify's MCP tools are never attached: the run options serve labhq's tools only.
    assert all("graphify" not in tool.name for tool in [*request.tools, *request.agent_tools])
    if switch:
        assert "## Code graph" in append
        assert f"{stub} query" in append
        assert f"--graph {graph}" in append
    else:
        assert "graphify" not in append


async def test_a_missing_binary_turns_the_measure_off_with_one_report(
    sessions: async_sessionmaker[AsyncSession],
    clock: FakeClock,
    tmp_path: Path,
    data_dir: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    index = index_with(data_dir, empty)
    built_graph(index, 1)
    prompts = prompts_with(index)
    ids = await manager(sessions, clock, {"graphify": True})

    with caplog.at_level(logging.WARNING, logger="labhq.economy.graphify"):
        for _ in range(2):
            script, status = await run_and_record(sessions, clock, tmp_path, prompts, ids)
            (request,) = script.requests
            assert status is RunStatus.SUCCEEDED
            assert "graphify" not in (request.system_prompt_append or "")
        assert await index.refresh(sessions, clock) == 0

    reports = [record for record in caplog.records if GRAPHIFY_MISSING in record.getMessage()]
    assert len(reports) == 1


@pytest.mark.posix_only("the graphify stub is a POSIX shell script")
async def test_the_refresh_loop_rebuilds_at_its_interval_and_after_head_moves(
    sessions: async_sessionmaker[AsyncSession], repo: Path, stub: Path, data_dir: Path
) -> None:
    stepped = SteppedClock()
    index = index_with(data_dir, stub.parent, refresh_seconds=300)
    async with sessions() as db:
        now = stepped.now()
        db.add(Project(name="demo", repo_path=str(repo), created_at=now, updated_at=now))
        await db.commit()
    passes = Passes()

    async def step() -> int:
        return await index.refresh(sessions, stepped)

    loop = asyncio.create_task(run_loop("graphify", 60, passes.watch("graphify", step), stepped))
    try:
        await passes.reached("graphify", 1)
        for tick in range(1, 11):
            await stepped.tick(60)
            await passes.reached("graphify", tick + 1)
        # Built when the project appeared, then every 300 seconds: at 0, 300 and 600.
        assert len(calls(stub)) == 3

        # A merge moves HEAD; the next pass rebuilds without waiting for the interval.
        commit_file(repo, "merged.txt")
        await stepped.tick(60)
        await passes.reached("graphify", 12)
        assert len(calls(stub)) == 4
    finally:
        loop.cancel()
        await asyncio.gather(loop, return_exceptions=True)


def test_the_program_and_the_prompt_registry_carry_graphify() -> None:
    spec = next(spec for spec in default_loops if spec.name == "graphify")
    assert spec.interval_setting == "graphify_interval_seconds"
    assert GRAPHIFY_SECTION in [section.name for section in builtin_registry().sections()]


def test_the_default_section_stays_out_for_agents_without_the_switch() -> None:
    agent = Agent(
        id=1,
        project_id=1,
        role="manager",
        title="M",
        adapter="fake",
        config={},
        created_at=datetime(2026, 10, 3, tzinfo=UTC),
        updated_at=datetime(2026, 10, 3, tzinfo=UTC),
    )
    assert default_section(agent, None) is None
