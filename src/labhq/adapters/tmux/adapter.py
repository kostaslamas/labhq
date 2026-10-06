"""The `tmux` adapter: any CLI agent in a session of labhq's private tmux server (ADR 0003).

One run is one session, named after the run, and one turn. The adapter polls the pane:
changes become `screen` events, new lines matching the kind's `reply_pattern` also become
`assistant` events, and the turn ends on the agent's own signal (or quiescence,
or its exit). Before the session closes it reads what the engine needs afterwards: the
statusline document, the screen after the agent's `usage_command`, and the final screen.
It never interprets usage itself; `labhq.usage` does, after the run.

Session ids are stored as `<kind>:<id>`, so a run on another agent kind (a fallback) never
tries to resume a conversation its CLI does not have.

Tools cannot cross into the agent's process, so each tool set is a `labhq mcp` command the
CLI starts over stdio: `mcp agent --run N` for the run agent's engine tools, and the
request's `tools_server` for a run's own tools (the Call Center's `mcp internal --call N`).
A run's own tools replace the built-in ones, so only a CLI that can drop those runs them.
"""

import asyncio
import json
import os
import re
import shlex
import shutil
import uuid
from collections.abc import AsyncIterator, Callable, Mapping
from datetime import timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from labhq.adapters.base import AdapterError, AdapterEvent, AdapterResult, RunRequest
from labhq.adapters.tmux.agents import (
    LAUNCHES,
    AgentKind,
    AgentKinds,
    LaunchContext,
    SessionIdSource,
    default_python,
)
from labhq.adapters.tmux.blocking import (
    BlockingScreen,
    blocking_screen,
    created_by_labhq,
    selected_line,
)
from labhq.adapters.tmux.environment import session_environment
from labhq.adapters.tmux.server import TmuxServer
from labhq.adapters.tmux.tools import TOOL_LAUNCHES, ToolServer
from labhq.adapters.tmux.turns import Watch, quiescent, screen_delta, turn_ended
from labhq.clock import Clock

INTERRUPT_REASON = "interrupt_sent"
SIGNAL_FILE = "turn-end.json"
# Written when a persistent pane's turn ends, removed when the next one starts: its presence
# means the pane is idle and says since when (`labhq.adapters.tmux.idle`).
IDLE_FILE = "idle-since"
STATUSLINE_FILE = "statusline.json"
# The last lines of the pane are what a limit notice or a usage report occupies.
FINAL_SCREEN_LINES = 80
OWN_TOOLS_SERVER = "labhq"
AGENT_TOOLS_SERVER = "labhq-agent"
SETTINGS_PREFIX = "LABHQ_"
BLOCKED_REASON = "blocked_dialog"
STALLED_REASON = "no_progress"


class TmuxAgentConfig(BaseModel):
    """The keys of `agents.config` this adapter reads; other keys belong to other modules."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    agent: str
    poll_seconds: float = Field(default=0.5, gt=0)
    quiescence_seconds: float = Field(default=10.0, gt=0)
    # After an interrupt, the turn is over once the screen settles for this long.
    interrupt_settle_seconds: float = Field(default=3.0, gt=0)
    usage_settle_seconds: float = Field(default=2.0, gt=0)
    usage_timeout_seconds: float = Field(default=30.0, gt=0)
    # A turn whose screen does not change for this long is stuck on something unseen. A
    # working agent redraws its spinner every second, so a quiet pane is not a thinking one.
    no_progress_seconds: float = Field(default=300.0, gt=0)


def guard_hook_command(python: str) -> str:
    return shlex.join([python, "-m", "labhq.guards.hook_command"])


def replies(kind: AgentKind, lines: list[str], seen: set[str]) -> list[str]:
    """New lines that are the agent's own output; a redrawn line is reported once."""
    if kind.reply_pattern is None:
        return []
    pattern = re.compile(kind.reply_pattern)
    found = [line for line in dict.fromkeys(lines) if line not in seen and pattern.search(line)]
    seen.update(found)
    return found


def session_name(run_id: int) -> str:
    """The tmux session of a run; `tmux -L labhq attach -t run-<id>` watches it."""
    return f"run-{run_id}"


def split_session(stored: str | None) -> tuple[str | None, str | None]:
    if not stored or ":" not in stored:
        return None, None
    kind, _, session = stored.partition(":")
    return kind, session


def _new_uuid(kind: AgentKind) -> str:
    return str(uuid.uuid4())


def _no_id(kind: AgentKind) -> str | None:
    return None


def _fixed(kind: AgentKind) -> str | None:
    return kind.session_key


# How a fresh session gets its id before the agent starts.
INITIAL_IDS: dict[SessionIdSource, Callable[[AgentKind], str | None]] = {
    SessionIdSource.ASSIGNED: _new_uuid,
    SessionIdSource.SIGNAL: _no_id,
    SessionIdSource.FIXED: _fixed,
}


class TmuxAdapter:
    def __init__(
        self,
        *,
        server: TmuxServer,
        kinds: AgentKinds,
        clock: Clock,
        environ: Mapping[str, str] | None = None,
        python: str | None = None,
        owned_root: Path | None = None,
    ) -> None:
        self._server = server
        self._kinds = kinds
        self._clock = clock
        self._environ = environ if environ is not None else os.environ
        self._python = python or default_python()
        # Directories under this root were created by labhq; only there may a trust
        # dialog be answered for the agent.
        self._owned_root = owned_root
        self._cwd: Path | None = None
        # (terminal reason, message) once the run cannot go on without a person.
        self._blocked: tuple[str, str] | None = None
        self._name: str | None = None
        self._kind: AgentKind | None = None
        self._config: TmuxAgentConfig | None = None
        self._run_dir: Path | None = None
        self._session_id: str | None = None
        self._interrupted = False
        self._result: AdapterResult | None = None
        self._persistent = False
        self._initial_screen = ""

    @property
    def clock(self) -> Clock:
        return self._clock

    async def start(self, request: RunRequest) -> None:
        if self._name is not None:
            raise AdapterError("an adapter instance serves one run")
        if request.cwd is None:
            raise AdapterError("the tmux adapter needs a working directory")
        config = TmuxAgentConfig.model_validate(dict(request.config))
        kind = self._kinds.get(config.agent)
        name = request.persistent_tmux_session or (
            session_name(request.run_id)
            if request.run_id is not None
            else f"run-{uuid.uuid4().hex}"
        )
        self._persistent = request.persistent_tmux_session is not None
        run_dir = self._server.state_dir / "runs" / name
        if not self._persistent:
            shutil.rmtree(run_dir, ignore_errors=True)
        run_dir.mkdir(parents=True, exist_ok=self._persistent)
        self._name, self._kind, self._config, self._run_dir = name, kind, config, run_dir
        self._cwd = request.cwd
        variables = session_environment(self._environ)
        if self._persistent:
            variables["LABHQ_CEO_SESSION"] = name
            (run_dir / IDLE_FILE).unlink(missing_ok=True)
            signal = self._read(SIGNAL_FILE)
            prior = _json_object(signal) if signal else None
            for filename in (SIGNAL_FILE, STATUSLINE_FILE):
                (run_dir / filename).unlink(missing_ok=True)
            if await asyncio.to_thread(self._server.has_session, name):
                existing = await asyncio.to_thread(self._server.show_environment, name)
                if existing.get("LABHQ_CEO_SESSION") != name:
                    raise AdapterError(f"tmux session {name!r} is not managed by labhq")
                _, previous_id = split_session(request.resume_session_id)
                self._session_id = previous_id or (
                    str(prior["session_id"]) if prior and prior.get("session_id") else None
                )
                state = await asyncio.to_thread(self._server.pane_state, name)
                if not state.dead:
                    self._initial_screen = await asyncio.to_thread(self._server.capture, name)
                    await self.send(request.persistent_turn_prompt or request.prompt)
                    return
                argv = self._argv(kind, request, run_dir)
                await asyncio.to_thread(
                    self._server.respawn_session,
                    name,
                    cwd=request.cwd,
                    argv=argv,
                    variables=variables,
                )
                return
        argv = self._argv(kind, request, run_dir)
        await asyncio.to_thread(
            self._server.new_session,
            name,
            cwd=request.cwd,
            argv=argv,
            variables=variables,
        )

    async def events(self) -> AsyncIterator[AdapterEvent]:
        name, kind, config = self._started()
        yield AdapterEvent("agent", {"kind": kind.name, "session": name})
        watch = Watch(screen=self._initial_screen, last_change_at=self._clock.now())
        quiet = timedelta(seconds=config.quiescence_seconds)
        settle = timedelta(seconds=config.interrupt_settle_seconds)
        replied: set[str] = set()
        answered: set[str] = set()
        stalled = timedelta(seconds=config.no_progress_seconds)
        while True:
            await self._clock.sleep(config.poll_seconds)
            screen = await asyncio.to_thread(self._server.capture, name)
            now = self._clock.now()
            if screen != watch.screen:
                lines = screen_delta(watch.screen, screen)
                yield AdapterEvent("screen", {"lines": lines})
                for line in replies(kind, lines, replied):
                    yield AdapterEvent("assistant", {"text": line})
                watch.screen, watch.last_change_at, watch.changed = screen, now, True
            watch.signal = self._read(SIGNAL_FILE)
            state = await asyncio.to_thread(self._server.pane_state, name)
            if state.dead:
                break
            if turn_ended(watch, kind, now, quiet):
                break
            if await self._answer_or_block(kind, screen, answered):
                break
            if now - watch.last_change_at >= stalled:
                self._blocked = (
                    STALLED_REASON,
                    f"the agent showed no progress for {config.no_progress_seconds:g}s",
                )
                break
            if self._interrupted and quiescent(watch, now, settle):
                break
        async for event in self._after_turn(
            watch.screen, alive=not state.dead and self._blocked is None
        ):
            yield event
        self._result = self._final_result(kind, watch, state.exit_status, state.dead)
        yield AdapterEvent(
            "result",
            {"subtype": self._result.subtype, "terminal_reason": self._result.terminal_reason},
        )

    async def send(self, text: str) -> None:
        name, _, _ = self._started()
        await asyncio.to_thread(self._server.send_keys, name, text, literal=True)
        await asyncio.to_thread(self._server.send_keys, name, "Enter")

    async def interrupt(self) -> None:
        name, kind, _ = self._started()
        self._interrupted = True
        await asyncio.to_thread(self._server.send_keys, name, *kind.interrupt_keys)

    def result(self) -> AdapterResult:
        if self._result is None:
            raise AdapterError("the run has no result yet")
        return self._result

    async def close(self) -> None:
        name, self._name = self._name, None
        if name is not None and not self._persistent:
            await asyncio.to_thread(self._server.kill_session, name)
        if self._run_dir is not None and not self._persistent:
            shutil.rmtree(self._run_dir, ignore_errors=True)
        if self._run_dir is not None and self._persistent and name is not None:
            (self._run_dir / IDLE_FILE).write_text(self._clock.now().isoformat(), encoding="utf-8")

    def _argv(self, kind: AgentKind, request: RunRequest, run_dir: Path) -> list[str]:
        stored_kind, stored_id = split_session(request.resume_session_id)
        resuming = kind.resume is not None and stored_kind == kind.name and bool(stored_id)
        template = kind.resume if resuming and kind.resume is not None else kind.start
        self._session_id = stored_id if resuming else INITIAL_IDS[kind.session_id](kind)
        context = LaunchContext(
            python=self._python,
            signal_path=run_dir / SIGNAL_FILE,
            statusline_path=run_dir / STATUSLINE_FILE,
            guard_hook=guard_hook_command(self._python),
        )
        values = {
            "prompt": self._prompt(request),
            "session_id": self._session_id or "",
            "signal_path": str(run_dir / SIGNAL_FILE),
            "guard_hook": context.guard_hook,
        }
        words = [word.format_map(values) for word in template]
        extra = LAUNCHES[kind.launch](context) if kind.launch is not None else []
        extra += self._tool_words(kind, request, run_dir)
        return [words[0], *extra, *words[1:]]

    @staticmethod
    def _prompt(request: RunRequest) -> str:
        if request.system_prompt_append:
            return f"{request.system_prompt_append}\n\n{request.prompt}"
        return request.prompt

    def _tool_words(self, kind: AgentKind, request: RunRequest, run_dir: Path) -> list[str]:
        own = bool(request.tools)
        servers = self._tool_servers(request)
        if not servers:
            return []
        launch = TOOL_LAUNCHES[kind.tool_launch] if kind.tool_launch is not None else None
        if own and (launch is None or launch.exclusive is None):
            raise AdapterError(
                f"{kind.name} cannot run with only its own tools: its CLI cannot drop its "
                "built-in shell and file tools"
            )
        if launch is None:
            # Engine tools are an addition; a CLI that takes no MCP server works without them.
            return []
        exclusive = launch.exclusive if own and launch.exclusive is not None else ()
        return [*launch.attach(run_dir, servers), *exclusive]

    def _tool_servers(self, request: RunRequest) -> list[ToolServer]:
        env = {k: v for k, v in self._environ.items() if k.startswith(SETTINGS_PREFIX)}
        labhq = (self._python, "-m", "labhq")
        servers: list[ToolServer] = []
        if request.tools:
            if not request.tools_server:
                raise AdapterError("the run's own tools name no stdio server to serve them")
            servers.append(ToolServer(OWN_TOOLS_SERVER, (*labhq, *request.tools_server), env))
        if request.agent_tools and request.run_id is not None:
            argv: tuple[str, ...] = (*labhq, "mcp", "agent", "--run", str(request.run_id))
            if request.persistent_tmux_session:
                argv += ("--follow-agent",)
            servers.append(ToolServer(AGENT_TOOLS_SERVER, argv, env))
        return servers

    async def _after_turn(self, screen: str, *, alive: bool) -> AsyncIterator[AdapterEvent]:
        statusline = self._read(STATUSLINE_FILE)
        if statusline:
            document = _json_object(statusline)
            if document is not None:
                yield AdapterEvent("statusline", document)
        kind = self._kind
        assert kind is not None
        if alive and kind.usage_command is not None and not self._interrupted:
            usage = await self._usage_screen(kind.usage_command, screen)
            yield AdapterEvent("usage_screen", {"text": usage})
        tail = "\n".join(screen.splitlines()[-FINAL_SCREEN_LINES:])
        yield AdapterEvent("screen_final", {"text": tail})

    async def _usage_screen(self, command: str, before: str) -> str:
        name, _, config = self._started()
        await asyncio.to_thread(self._server.send_keys, name, command, literal=True)
        await asyncio.to_thread(self._server.send_keys, name, "Enter")
        watch = Watch(screen=before, last_change_at=self._clock.now())
        deadline = self._clock.now() + timedelta(seconds=config.usage_timeout_seconds)
        settle = timedelta(seconds=config.usage_settle_seconds)
        while self._clock.now() < deadline:
            await self._clock.sleep(config.poll_seconds)
            screen = await asyncio.to_thread(self._server.capture, name)
            now = self._clock.now()
            if screen != watch.screen:
                watch.screen, watch.last_change_at, watch.changed = screen, now, True
            elif quiescent(watch, now, settle):
                break
        return "\n".join(screen_delta(before, watch.screen))

    async def _answer_or_block(self, kind: AgentKind, screen: str, answered: set[str]) -> bool:
        """Answer a trust dialog of a directory labhq created; True if the run is now blocked."""
        found = blocking_screen(kind.blocking_screens, screen)
        if found is None or found.name in answered:
            return False
        if found.accept_option is not None and self._cwd is not None:
            if created_by_labhq(self._cwd, self._owned_root):
                answered.add(found.name)
                if await self._choose(found, found.accept_option):
                    return False
                self._blocked = (
                    BLOCKED_REASON,
                    f"{found.reason}, and {found.accept_option!r} could not be selected",
                )
                return True
            self._blocked = (
                BLOCKED_REASON,
                f"{found.reason}, and {self._cwd} is not a directory labhq created",
            )
            return True
        self._blocked = (BLOCKED_REASON, found.reason)
        return True

    async def _choose(self, dialog: BlockingScreen, option: str) -> bool:
        """Move the cursor to `option`, looking at the pane after every press, then confirm.

        Enter is sent only with the cursor on the option: on any other option it would
        answer the dialog the wrong way.
        """
        name, _, _ = self._started()
        for _ in range(dialog.max_presses + 1):
            screen = await asyncio.to_thread(self._server.capture, name)
            line = selected_line(screen)
            if line is not None and option in line:
                await asyncio.to_thread(self._server.send_keys, name, dialog.confirm_key)
                return True
            await asyncio.to_thread(self._server.send_keys, name, dialog.select_key)
            await self._clock.sleep(self._started()[2].poll_seconds)
        return False

    def _final_result(
        self, kind: AgentKind, watch: Watch, exit_status: int | None, dead: bool
    ) -> AdapterResult:
        session_id = self._discovered_session(kind, watch.signal)
        stored = f"{kind.name}:{session_id}" if session_id else None
        if self._interrupted:
            return AdapterResult(
                subtype="error_during_execution",
                is_error=True,
                session_id=stored,
                terminal_reason=INTERRUPT_REASON,
                num_turns=1,
            )
        if self._blocked is not None:
            terminal_reason, message = self._blocked
            return AdapterResult(
                subtype="error_blocked",
                is_error=True,
                session_id=stored,
                terminal_reason=terminal_reason,
                num_turns=1,
                errors=[message],
            )
        failed = dead and exit_status not in (0, None)
        errors = [f"the agent exited with status {exit_status}"] if failed else []
        return AdapterResult(
            subtype="error_exit" if failed else "success",
            is_error=failed,
            session_id=stored,
            terminal_reason="process_exit" if dead else "completed",
            num_turns=1,
            errors=errors,
            text=self._reply(kind, watch.signal),
        )

    def _reply(self, kind: AgentKind, signal: str | None) -> str | None:
        payload = _json_object(signal) if signal and kind.reply_key is not None else None
        reply = payload.get(kind.reply_key) if payload and kind.reply_key else None
        return reply if isinstance(reply, str) else None

    def _discovered_session(self, kind: AgentKind, signal: str | None) -> str | None:
        if kind.session_id is not SessionIdSource.SIGNAL or kind.session_key is None:
            return self._session_id
        payload = _json_object(signal) if signal else None
        found = payload.get(kind.session_key) if payload else None
        return str(found) if found else self._session_id

    def _read(self, filename: str) -> str | None:
        assert self._run_dir is not None
        path = self._run_dir / filename
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None

    def _started(self) -> tuple[str, AgentKind, TmuxAgentConfig]:
        if self._name is None or self._kind is None or self._config is None:
            raise AdapterError("start() was not called")
        return self._name, self._kind, self._config


def _json_object(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None
