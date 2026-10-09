"""Ask the owner to log a tool in: start its own login command, pass the link on, confirm.

1. A check (or a run that stopped on the tool's login dialog) finds the tool logged out.
2. labhq starts the tool's own login command in a private tmux pane and takes the link from
   the screen. At most one request is pending per tool and account.
3. The link goes to every notification channel and to the Call Center (a CEO report).
4. The owner finishes in a browser; the next re-check passes and the CEO confirms.

The tool stores its own credentials. labhq sees a link, never a credential, and relays no
code: when the tool asks for one, the notification says to paste it in the terminal.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.approvals.registry import Registry
from labhq.clock import Clock
from labhq.db.enums import LoginStage
from labhq.db.models import CeoReport, LoginRequest
from labhq.logins import copy
from labhq.logins.check import CommandRunner, LoginState, check_login, run_command
from labhq.logins.panes import LoginPanes, pane_name
from labhq.logins.settings import LoginSettings, get_login_settings
from labhq.logins.tools import LoginTool, login_tools
from labhq.notify.outbox import enqueue

NOTIFICATION_KIND = "login"
DEFAULT_ACCOUNT = "default"
REPORT_REF = "login:{tool}"


@dataclass(frozen=True)
class LoginOutcome:
    # None when the tool was already logged in (or could not be told).
    request: LoginRequest | None
    # False when a request for this tool and account was already pending.
    created: bool
    state: LoginState


class LoginService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        clock: Clock,
        panes: LoginPanes,
        *,
        work_dir: Path,
        runner: CommandRunner = run_command,
        settings: LoginSettings | None = None,
        tools: Registry[LoginTool] = login_tools,
    ) -> None:
        self._sessions = sessions
        self._clock = clock
        self._panes = panes
        self._work_dir = work_dir
        self._runner = runner
        self._settings = settings or get_login_settings()
        self._tools = tools

    async def ensure(self, tool_name: str, account: str = DEFAULT_ACCOUNT) -> LoginOutcome:
        """Check the tool; ask the owner to log in only when it is certainly logged out."""
        tool = self._tools.get(tool_name)
        state = await asyncio.to_thread(
            check_login,
            tool,
            runner=self._runner,
            timeout=self._settings.status_timeout_seconds,
        )
        if state is not LoginState.LOGGED_OUT:
            return LoginOutcome(None, False, state)
        return await self.request(tool_name, account)

    async def request(self, tool_name: str, account: str = DEFAULT_ACCOUNT) -> LoginOutcome:
        """Start the login flow unless one is pending for this tool and account."""
        tool = self._tools.get(tool_name)
        now = self._clock.now()
        async with self._sessions() as db:
            await self._expire_overdue(db, now)
            existing = await _pending(db, tool.name, account)
            if existing is not None:
                await db.commit()
                return LoginOutcome(existing, False, LoginState.LOGGED_OUT)
            row = LoginRequest(
                tool=tool.name,
                account=account,
                stage=LoginStage.PENDING,
                created_at=now,
                expires_at=now + timedelta(seconds=tool.timeout_seconds),
            )
            try:
                async with db.begin_nested():
                    db.add(row)
            except IntegrityError:
                # Another process won the race for the one pending request.
                raced = await _pending(db, tool.name, account)
                assert raced is not None
                return LoginOutcome(raced, False, LoginState.LOGGED_OUT)
            await db.commit()
            row_id = row.id
        url, awaits_code, pane = await self._start(tool, account, row_id)
        async with self._sessions() as db:
            row = await db.get_one(LoginRequest, row_id)
            row.url, row.awaits_code, row.pane = url, awaits_code, pane
            if url is None:
                row.stage = LoginStage.FAILED
                row.detail = "no login link appeared"
                self._kill(pane)
            await self._announce(db, tool, row)
            await db.commit()
            await db.refresh(row)
        return LoginOutcome(row, True, LoginState.LOGGED_OUT)

    async def recheck_pending(self) -> int:
        """Re-check every pending request; returns how many ended (completed or expired)."""
        now = self._clock.now()
        ended = 0
        async with self._sessions() as db:
            rows = list(
                await db.scalars(
                    select(LoginRequest).where(LoginRequest.stage == LoginStage.PENDING)
                )
            )
            for row in rows:
                tool = self._tools.get(row.tool)
                if now >= row.expires_at:
                    await self._end(db, tool, row, LoginStage.EXPIRED, copy.EXPIRED, now)
                    ended += 1
                    continue
                screen = await asyncio.to_thread(self._panes.screen, row.pane) if row.pane else ""
                if await self._logged_in(tool, row, screen):
                    await self._end(db, tool, row, LoginStage.COMPLETED, copy.CONFIRMED, now)
                    ended += 1
                elif not row.awaits_code and tool.asks_for_code(screen):
                    row.awaits_code = True
                    await self._announce_code(db, tool, row)
            await db.commit()
        return ended

    async def _logged_in(self, tool: LoginTool, row: LoginRequest, screen: str) -> bool:
        if tool.status is not None:
            state = await asyncio.to_thread(
                check_login,
                tool,
                runner=self._runner,
                timeout=self._settings.status_timeout_seconds,
            )
            return state is LoginState.LOGGED_IN
        # No status command: the dialog is gone from a pane that is still running.
        alive = bool(row.pane) and await asyncio.to_thread(self._panes.alive, row.pane or "")
        if not alive or not screen:
            return False
        return check_login(tool, screen=screen) is LoginState.LOGGED_IN

    async def _start(
        self, tool: LoginTool, account: str, request_id: int
    ) -> tuple[str | None, bool, str | None]:
        if tool.login is None:
            return None, False, None
        name = pane_name(tool.name, account, request_id)
        try:
            await asyncio.to_thread(self._panes.start, name, tool.login, self._work_dir)
        except Exception:
            return None, False, None
        deadline = self._clock.now() + timedelta(seconds=self._settings.url_wait_seconds)
        screen = ""
        while True:
            screen = await asyncio.to_thread(self._panes.screen, name)
            url = tool.find_url(screen)
            if url is not None:
                return url, tool.asks_for_code(screen), name
            alive = await asyncio.to_thread(self._panes.alive, name)
            if not alive or self._clock.now() >= deadline:
                return None, False, name
            await self._clock.sleep(self._settings.poll_seconds)

    async def _announce(self, db: AsyncSession, tool: LoginTool, row: LoginRequest) -> None:
        if row.url is not None:
            text = copy.WITH_LINK.format(tool=tool.display_name, link=row.url)
            if row.awaits_code:
                text += copy.WITH_CODE.format(socket=self._panes.socket, pane=row.pane)
        elif tool.login is None:
            text = copy.NO_LOGIN_COMMAND.format(tool=tool.display_name)
        else:
            text = copy.NO_LINK.format(tool=tool.display_name, command=" ".join(tool.login))
        await self._tell(db, tool, row, key=f"login:{row.id}:link", text=text, click_url=row.url)

    async def _announce_code(self, db: AsyncSession, tool: LoginTool, row: LoginRequest) -> None:
        text = copy.WITH_CODE.format(socket=self._panes.socket, pane=row.pane).strip()
        await self._tell(db, tool, row, key=f"login:{row.id}:code", text=text, click_url=None)

    async def _end(
        self,
        db: AsyncSession,
        tool: LoginTool,
        row: LoginRequest,
        stage: LoginStage,
        template: str,
        now: datetime,
    ) -> None:
        row.stage = stage
        if stage is LoginStage.COMPLETED:
            row.completed_at = now
        self._kill(row.pane)
        text = template.format(tool=tool.display_name)
        await self._tell(db, tool, row, key=f"login:{row.id}:{stage}", text=text, click_url=None)

    async def _tell(
        self,
        db: AsyncSession,
        tool: LoginTool,
        row: LoginRequest,
        *,
        key: str,
        text: str,
        click_url: str | None,
    ) -> None:
        """One outbox row (every channel gets it) and one CEO report (the Call Center)."""
        now = self._clock.now()
        await enqueue(
            db,
            kind=NOTIFICATION_KIND,
            subject=f"login:{tool.name}",
            title=copy.TITLE.format(tool=tool.display_name),
            body=text,
            click_url=click_url,
            idempotency_key=key,
            now=now,
        )
        db.add(
            CeoReport(
                agent_id=None,
                text=text,
                refs=[REPORT_REF.format(tool=tool.name)],
                task_id=None,
                created_at=now,
            )
        )

    def _kill(self, pane: str | None) -> None:
        if pane:
            self._panes.kill(pane)

    async def _expire_overdue(self, db: AsyncSession, now: datetime) -> None:
        rows = await db.scalars(
            select(LoginRequest).where(
                LoginRequest.stage == LoginStage.PENDING, LoginRequest.expires_at <= now
            )
        )
        for row in rows:
            await self._end(
                db, self._tools.get(row.tool), row, LoginStage.EXPIRED, copy.EXPIRED, now
            )
        await db.flush()


async def _pending(db: AsyncSession, tool: str, account: str) -> LoginRequest | None:
    return await db.scalar(
        select(LoginRequest).where(
            LoginRequest.tool == tool,
            LoginRequest.account == account,
            LoginRequest.stage == LoginStage.PENDING,
        )
    )
