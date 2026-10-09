"""Analyse one project on the owner's request: estimate, confirm, run, write an md file.

Nothing here runs by itself and there is no "analyse everything". The request names one
project; it records an `analyse_project` approval that carries the estimate, the kind and the
sessions to read. The analysis starts only when the owner approves that approval, which is the
confirmation of the shown estimate. The model that runs it is a kind labhq has available,
chosen by `chooser`, not the tool that made the sessions.
"""

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.adapters import AdapterRegistry
from labhq.adapters import default_registry as builtin_adapters
from labhq.approvals import ApprovalService
from labhq.ceoreports import record_report
from labhq.clock import Clock, SystemClock
from labhq.db import create_engine, session_factory
from labhq.db.enums import AgentStatus, RunStatus
from labhq.db.models import Agent, RunEvent
from labhq.hierarchy import WORKER, find_ceo
from labhq.inventory.chooser import Runner, choose_runner, default_runners
from labhq.inventory.estimate import Estimate, estimate, tracked_bytes
from labhq.inventory.gather import build_prompt, gather, tracked_files
from labhq.inventory.model import ProjectInventory, SavedEntry
from labhq.inventory.scan import SessionScanner
from labhq.inventory.settings import InventorySettings, get_inventory_settings
from labhq.money import format_micros
from labhq.runs import RunService
from labhq.settings import Settings

ANALYSE_PROJECT = "analyse_project"
ANALYST_TITLE = "Session analyst"


class AnalysisError(RuntimeError):
    pass


class SessionRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tool: str
    session_id: str
    updated_at: AwareDatetime
    location: str | None = None


class AnalysePayload(BaseModel):
    """What the owner confirms: one project, who runs it, what it costs, what it reads."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    project: str = Field(min_length=1)
    root: str
    has_repo: bool
    kind: str
    account: str | None = None
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_micros: int = Field(ge=0)
    sessions: tuple[SessionRef, ...]


def entry_of(ref: SessionRef, folder: Path) -> SavedEntry:
    location = Path(ref.location) if ref.location else None
    return SavedEntry(ref.tool, ref.session_id, folder, ref.updated_at, location)


def estimate_text(payload: AnalysePayload) -> str:
    who = payload.kind + (f" ({payload.account})" if payload.account else "")
    tokens = payload.input_tokens + payload.output_tokens
    return (
        f"Analysing {payload.project} would read {len(payload.sessions)} sessions and use about "
        f"{tokens:,} tokens, roughly {format_micros(payload.cost_micros, 2)}, on {who}."
    )


@dataclass(frozen=True)
class AnalysisRequest:
    approval_id: int
    payload: AnalysePayload
    estimate: Estimate

    @property
    def text(self) -> str:
        return f"{estimate_text(self.payload)} Approve approval {self.approval_id} to start."


def find_project(scan_projects: list[ProjectInventory], reference: str) -> ProjectInventory:
    """A project by folder name or path; ambiguity and absence are errors, not guesses."""
    wanted = reference.strip().casefold()
    matches = [p for p in scan_projects if wanted in (p.name.casefold(), str(p.root).casefold())]
    if not matches:
        raise AnalysisError(f"no project named {reference!r} has agent sessions")
    if len(matches) > 1:
        paths = ", ".join(str(p.root) for p in matches)
        raise AnalysisError(f"{reference!r} is ambiguous: {paths}")
    return matches[0]


class Analyses:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        clock: Clock,
        scanner: SessionScanner | None = None,
        approvals: ApprovalService | None = None,
        settings: InventorySettings | None = None,
        runners: Mapping[str, Runner] | None = None,
    ) -> None:
        self._sessions = sessions
        self._clock = clock
        self._settings = settings or get_inventory_settings()
        self._scanner = scanner or SessionScanner(settings=self._settings, clock=clock)
        self._approvals = approvals or ApprovalService(sessions, clock=clock)
        self._runners = runners

    async def request(self, reference: str) -> AnalysisRequest:
        """Estimate the analysis of one project and record the approval that starts it."""
        inventory = await asyncio.to_thread(self._scanner.scan)
        project = find_project(inventory.projects, reference)
        refs = tuple(
            SessionRef(
                tool=s.tool,
                session_id=s.session_id,
                updated_at=s.last_activity,
                location=str(s.location) if s.location else None,
            )
            for s in project.sessions
            if s.session_id is not None and s.last_activity is not None
        )
        entries = [entry_of(ref, project.root) for ref in refs]
        async with self._sessions() as db:
            choice = await choose_runner(
                db,
                self._clock,
                self._settings,
                original_tools={s.tool for s in project.sessions},
                runners=self._runners,
            )
        code = await asyncio.to_thread(_code_bytes, project)
        figures = estimate(
            kind=choice.runner.name,
            account=choice.account,
            code_bytes=code,
            entries=entries,
            settings=self._settings,
        )
        payload = AnalysePayload(
            project=project.name,
            root=str(project.root),
            has_repo=project.has_repo,
            kind=figures.kind,
            account=figures.account,
            input_tokens=figures.input_tokens,
            output_tokens=figures.output_tokens,
            cost_micros=figures.cost_micros,
            sessions=refs,
        )
        approval = await self._approvals.request(ANALYSE_PROJECT, payload.model_dump(mode="json"))
        return AnalysisRequest(approval.id, payload, figures)


def _code_bytes(project: ProjectInventory) -> int:
    return tracked_bytes(tracked_files(project.root)) if project.has_repo else 0


@dataclass(frozen=True)
class AnalysisEngine:
    """Everything the `analyse_project` executor needs besides its payload."""

    clock: Clock = field(default_factory=SystemClock)
    registry: AdapterRegistry = builtin_adapters
    settings: Callable[[], InventorySettings] = get_inventory_settings
    runners: Mapping[str, Runner] | None = None
    database_url: Callable[[], str] = lambda: Settings().resolved_database_url
    data_dir: Callable[[], Path] = lambda: Settings().data_dir

    def run(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Called from the approval service's worker thread, with only the payload."""
        return asyncio.run(self.analyse(AnalysePayload.model_validate(payload)))

    async def analyse(self, request: AnalysePayload) -> dict[str, Any]:
        root = Path(request.root)
        if not root.is_dir():
            raise AnalysisError(f"project folder {root} is gone")
        settings = self.settings()
        pool = self.runners if self.runners is not None else default_runners()
        runner = pool.get(request.kind)
        if runner is None:
            raise AnalysisError(f"no runner for kind {request.kind!r}")
        entries = [entry_of(ref, root) for ref in request.sessions]
        material = await asyncio.to_thread(gather, root, request.has_repo, entries, settings)
        prompt = build_prompt(request.project, root, material)
        engine = create_engine(self.database_url())
        sessions = session_factory(engine)
        try:
            text, run_id = await self._ask(sessions, runner, prompt)
            path = self._write(request, text)
            async with sessions() as db:
                ceo = await find_ceo(db)
                await record_report(
                    db,
                    self.clock,
                    agent_id=ceo.id if ceo else None,
                    text=f"Analysis of {request.project} is ready: {path}",
                )
                await db.commit()
        finally:
            await engine.dispose()
        return {"path": str(path), "run_id": run_id, "kind": request.kind}

    async def _ask(
        self, sessions: async_sessionmaker[AsyncSession], runner: Runner, prompt: str
    ) -> tuple[str, int]:
        agent_id = await self._analyst(sessions, runner)
        runs = RunService(sessions, clock=self.clock, registry=self.registry)
        scratch = self.data_dir() / "inventory" / "scratch"
        scratch.mkdir(parents=True, exist_ok=True)
        run = await runs.execute(agent_id=agent_id, task_id=None, prompt=prompt, cwd=scratch)
        if run.status is not RunStatus.SUCCEEDED:
            raise AnalysisError(f"the analysis run {run.id} ended {run.status}")
        async with sessions() as db:
            payload = await db.scalar(
                select(RunEvent.payload)
                .where(RunEvent.run_id == run.id, RunEvent.kind == "result")
                .order_by(RunEvent.seq.desc())
                .limit(1)
            )
        text = payload.get("result") if payload else None
        if not isinstance(text, str) or not text.strip():
            raise AnalysisError(f"the analysis run {run.id} returned no text")
        return text, run.id

    async def _analyst(self, sessions: async_sessionmaker[AsyncSession], runner: Runner) -> int:
        title = f"{ANALYST_TITLE} ({runner.name})"
        async with sessions() as db:
            found = await db.scalar(
                select(Agent).where(Agent.title == title, Agent.status != AgentStatus.RETIRED)
            )
            if found is not None:
                return found.id
            ceo = await find_ceo(db)
            now: datetime = self.clock.now()
            agent = Agent(
                project_id=None,
                role=WORKER,
                title=title,
                reports_to=ceo.id if ceo else None,
                adapter=runner.adapter,
                config={**runner.config, "tools": []},
                status=AgentStatus.ACTIVE,
                created_at=now,
                updated_at=now,
            )
            db.add(agent)
            await db.commit()
            return agent.id

    def _write(self, request: AnalysePayload, text: str) -> Path:
        directory = self.data_dir() / "inventory" / "analyses"
        directory.mkdir(parents=True, exist_ok=True)
        stamp = self.clock.now().strftime("%Y%m%d-%H%M%S")
        path = directory / f"{_slug(request.project)}-{stamp}.md"
        header = (
            f"# Session analysis: {request.project}\n\n"
            f"Folder: {request.root}\n\nRun on: {request.kind}"
            f"\n\nSessions: "
            + ", ".join(f"{s.tool} {s.session_id}" for s in request.sessions)
            + "\n\n"
        )
        path.write_text(header + text.strip() + "\n", encoding="utf-8")
        return path


def _slug(name: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in "-_" else "-" for c in name)
    return cleaned.strip("-") or "project"
