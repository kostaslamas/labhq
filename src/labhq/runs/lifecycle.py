"""A run from start to its terminal status, recorded as it happens.

Each event is committed with a fresh `heartbeat_at`, so the reaper sees a live run as
live. The terminal result sets the status through `labhq.runs.status`, writes one
`cost_events` row in micros through `labhq.money`, and stores the session for resume.
A long-lived agent's memory is seeded before the run and taken back after it, whatever
its status (`labhq.memory`).
"""

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.adapters import (
    Adapter,
    AdapterEvent,
    AdapterRegistry,
    AdapterResult,
    AgentTool,
    RunRequest,
)
from labhq.adapters import default_registry as builtin_adapters
from labhq.agenttools import AgentToolRegistry, ToolContext, bind
from labhq.agenttools import default_registry as builtin_agent_tools
from labhq.clock import Clock
from labhq.db.enums import RunStatus
from labhq.db.models import Agent, AgentTaskSession, CostEvent, Run, RunEvent, Task
from labhq.memory import AgentMemory, PreparedMemory
from labhq.money import usd_to_micros
from labhq.prompts import PromptRegistry
from labhq.prompts import default_registry as builtin_prompts
from labhq.runs.status import status_for
from labhq.settings import Settings
from labhq.usage.plan import agent_kind

TOKEN_COLUMNS = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)

MEMORY_EVENT = "memory_updated"
WARNING_EVENT = "warning"


def session_adapter(adapter: str, config: dict[str, Any]) -> str:
    """Name the CLI kind too: two tmux programs cannot resume each other's sessions."""
    return f"tmux:{agent_kind(adapter, config)}" if adapter == "tmux" else adapter


class RunStartError(RuntimeError):
    """The adapter failed to start. The run is already recorded as failed."""

    def __init__(self, run_id: int) -> None:
        super().__init__(f"run {run_id} failed to start")
        self.run_id = run_id


class RunService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        clock: Clock,
        registry: AdapterRegistry = builtin_adapters,
        memory: AgentMemory | None = None,
        prompts: PromptRegistry = builtin_prompts,
        agent_tools: AgentToolRegistry = builtin_agent_tools,
    ) -> None:
        self._sessions = sessions
        self._clock = clock
        self._registry = registry
        self._memory = memory if memory is not None else AgentMemory.from_settings(Settings())
        self._prompts = prompts
        self._agent_tools = agent_tools

    async def start(
        self,
        *,
        agent_id: int,
        task_id: int | None,
        prompt: str,
        cwd: Path | None = None,
        hooks: dict[str, Any] | None = None,
        run_id: int | None = None,
        resume_session_id: str | None = None,
        tools: Sequence[AgentTool] = (),
        config: dict[str, Any] | None = None,
        adapter: str | None = None,
        tools_server: Sequence[str] = (),
    ) -> "ActiveRun":
        """Start a run. `run_id` adopts a queued run instead of creating one.

        The scheduler needs the run id before the adapter starts, to take the task's
        checkout with it; it queues the run, checks out, then hands the id here.
        `resume_session_id` continues a session kept outside `agent_task_sessions`, such as
        a call's; it wins over the task's stored session. `config` is laid over
        `agents.config` for this run only, for example a fallback agent kind.
        """
        db = self._sessions()
        try:
            agent = await db.get_one(Agent, agent_id)
            selected_adapter = adapter or agent.adapter
            effective_config = {**agent.config, **(config or {})}
            task = await db.get_one(Task, task_id) if task_id is not None else None
            stored, resumable = await _stored_session(
                db, agent, task_id, selected_adapter, effective_config
            )
            if cwd is None and stored is not None and stored.cwd:
                # Sessions are stored per working directory; resume needs the same one.
                cwd = Path(stored.cwd)
            memory = self._memory.prepare(agent, cwd)
            if memory is not None:
                cwd, prompt = memory.cwd, memory.prompt(prompt)
            # Before the run turns running: a bad recipient or tool name fails the start.
            system_prompt_append = self._prompts.assemble(agent, task)
            agent_tool_specs = self._agent_tools.for_agent(agent.role, agent.config)
            now = self._clock.now()
            run = await _queued_run(db, run_id, agent_id, task_id, now)
            run.adapter = selected_adapter
            run.status = RunStatus.RUNNING
            run.session_id_before = resume_session_id or (
                stored.session_id if stored is not None and resumable else None
            )
            run.started_at = run.heartbeat_at = now
            await db.commit()
            tool_context = ToolContext(agent.id, run.id, self._sessions, self._clock)
            request = RunRequest(
                prompt=prompt,
                cwd=cwd,
                resume_session_id=run.session_id_before,
                config=effective_config,
                hooks=hooks,
                tools=tools,
                tools_server=tools_server,
                run_id=run.id,
                agent_tools=[bind(spec, tool_context) for spec in agent_tool_specs],
                system_prompt_append=system_prompt_append,
            )
            project_id = task.project_id if task is not None else agent.project_id
            active = ActiveRun(
                db, self._clock, self._registry.create(selected_adapter), run, self._memory, memory
            )
            await active.begin(request, project_id)
        except BaseException:
            await db.close()
            raise
        return active

    async def execute(
        self,
        *,
        agent_id: int,
        task_id: int | None,
        prompt: str,
        cwd: Path | None = None,
        hooks: dict[str, Any] | None = None,
        run_id: int | None = None,
        resume_session_id: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> Run:
        active = await self.start(
            agent_id=agent_id,
            task_id=task_id,
            prompt=prompt,
            cwd=cwd,
            hooks=hooks,
            run_id=run_id,
            resume_session_id=resume_session_id,
            config=config,
        )
        return await active.wait()


class ActiveRun:
    """A started run. `wait()` drives its stream; `send` and `interrupt` steer it meanwhile."""

    def __init__(
        self,
        db: AsyncSession,
        clock: Clock,
        adapter: Adapter,
        run: Run,
        memory: AgentMemory | None = None,
        prepared: PreparedMemory | None = None,
    ) -> None:
        self._db = db
        self._clock = clock
        self._adapter = adapter
        self.run = run
        self._memory = memory
        self._prepared = prepared
        self._seq = 0
        self._project_id: int | None = None
        self._cwd: Path | None = None
        self._session_adapter = run.adapter
        # The adapter's terminal result once `wait()` has finished it; None on a failure.
        self.result: AdapterResult | None = None

    @property
    def run_id(self) -> int:
        return self.run.id

    async def begin(self, request: RunRequest, project_id: int | None) -> None:
        self._project_id = project_id
        self._cwd = request.cwd
        self._session_adapter = session_adapter(self.run.adapter, dict(request.config))
        try:
            await self._adapter.start(request)
        except Exception as error:
            await self._fail(error)
            await self._adapter.close()
            raise RunStartError(self.run.id) from error

    async def send(self, text: str) -> None:
        await self._adapter.send(text)

    async def interrupt(self) -> None:
        await self._adapter.interrupt()

    async def note(self, kind: str, payload: dict[str, Any]) -> None:
        """Record an event the engine raises itself, such as a disabled hook."""
        await self._record(AdapterEvent(kind=kind, payload=payload))

    async def wait(self) -> Run:
        try:
            async for event in self._adapter.events():
                await self._record(event)
            result = self._adapter.result()
        except Exception as error:
            await self._fail(error)
        else:
            await self._finish(result)
        finally:
            try:
                await self._adapter.close()
                await self._keep_memory()
            finally:
                await self._db.close()
        return self.run

    async def _keep_memory(self) -> None:
        if self._memory is None or self._prepared is None:
            return
        try:
            update = self._memory.collect(self._prepared)
        except OSError as error:
            # A lost memory must stay visible on the run, not end it as failed.
            await self.note(WARNING_EVENT, {"memory": type(error).__name__, "message": str(error)})
            return
        if update is not None:
            await self.note(MEMORY_EVENT, update.as_event_payload())

    async def _record(self, event: AdapterEvent) -> None:
        now = self._clock.now()
        self._seq += 1
        self._db.add(
            RunEvent(
                run_id=self.run.id,
                seq=self._seq,
                kind=event.kind,
                payload=event.payload,
                created_at=now,
            )
        )
        self.run.heartbeat_at = now
        await self._db.commit()

    async def _finish(self, result: AdapterResult) -> None:
        self.result = result
        now = self._clock.now()
        run = self.run
        run.status = status_for(result)
        run.finished_at = run.heartbeat_at = now
        run.session_id_after = result.session_id
        run.usage = result.usage
        run.exit = {
            "subtype": result.subtype,
            "is_error": result.is_error,
            "terminal_reason": result.terminal_reason,
            "num_turns": result.num_turns,
            "errors": result.errors,
        }
        tokens = {name: int(result.usage.get(name) or 0) for name in TOKEN_COLUMNS}
        self._db.add(
            CostEvent(
                run_id=run.id,
                agent_id=run.agent_id,
                project_id=self._project_id,
                cost_micros=usd_to_micros(result.cost_usd if result.cost_usd is not None else 0),
                model=result.model,
                created_at=now,
                **tokens,
            )
        )
        if run.task_id is not None and result.session_id:
            await self._store_session(run.task_id, result.session_id, now)
        await self._db.commit()

    async def _fail(self, error: Exception) -> None:
        now = self._clock.now()
        self.run.status = RunStatus.FAILED
        self.run.finished_at = self.run.heartbeat_at = now
        self.run.exit = {"error": type(error).__name__, "message": str(error)}
        await self._db.commit()

    async def _store_session(self, task_id: int, session_id: str, now: datetime) -> None:
        cwd = str(self._cwd) if self._cwd is not None else None
        row = await self._db.scalar(
            select(AgentTaskSession).where(
                AgentTaskSession.agent_id == self.run.agent_id,
                AgentTaskSession.task_id == task_id,
            )
        )
        if row is None:
            self._db.add(
                AgentTaskSession(
                    agent_id=self.run.agent_id,
                    task_id=task_id,
                    adapter=self._session_adapter,
                    session_id=session_id,
                    cwd=cwd,
                    created_at=now,
                    updated_at=now,
                )
            )
            return
        row.adapter = self._session_adapter
        row.session_id = session_id
        row.cwd = cwd
        row.updated_at = now


async def _queued_run(
    db: AsyncSession, run_id: int | None, agent_id: int, task_id: int | None, now: datetime
) -> Run:
    if run_id is None:
        run = Run(agent_id=agent_id, task_id=task_id, adapter="", created_at=now)
        db.add(run)
        return run
    run = await db.get_one(Run, run_id)
    if run.status is not RunStatus.QUEUED or (run.agent_id, run.task_id) != (agent_id, task_id):
        raise ValueError(f"run {run_id} is not a queued run of this agent and task")
    return run


async def _stored_session(
    db: AsyncSession,
    agent: Agent,
    task_id: int | None,
    adapter: str,
    config: dict[str, Any],
) -> tuple[AgentTaskSession | None, bool]:
    if task_id is None:
        return None, False
    row = await db.scalar(
        select(AgentTaskSession).where(
            AgentTaskSession.agent_id == agent.id,
            AgentTaskSession.task_id == task_id,
        )
    )
    if row is None:
        return None, False
    key = session_adapter(adapter, config)
    if row.adapter == key:
        return row, True
    # Older tmux rows have no kind tag. Reuse only while the agent's configuration has not
    # changed since that session was stored; its next run writes a tagged row.
    if (
        row.adapter == adapter == "tmux"
        and key == session_adapter(agent.adapter, agent.config)
        and row.updated_at >= agent.updated_at
    ):
        return row, True
    return row, False
