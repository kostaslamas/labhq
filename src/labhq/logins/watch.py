"""The program's login duty: runs that stopped on a login dialog, and requests still waiting.

A run whose tool showed its login dialog ends as `blocked_dialog` with the dialog's reason.
Each pass turns such a run into a login request (at most one per tool and account) and
re-checks the pending ones, so the CEO confirms once the owner has logged in.
"""

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.adapters.tmux.adapter import BLOCKED_REASON
from labhq.approvals.registry import Registry
from labhq.clock import Clock, ensure_utc
from labhq.db.models import LoginRequest, Run
from labhq.logins.service import DEFAULT_ACCOUNT, LoginService
from labhq.logins.settings import LoginSettings, get_login_settings
from labhq.logins.tools import LoginTool, login_tools


def login_tool_of(run: Run, tools: Registry[LoginTool] = login_tools) -> LoginTool | None:
    """The tool whose login dialog ended this run, from the reason the adapter recorded."""
    exit_ = run.exit or {}
    if exit_.get("terminal_reason") != BLOCKED_REASON:
        return None
    reasons = [str(error) for error in exit_.get("errors") or []]
    for name in tools:
        tool = tools.get(name)
        if tool.screen_reason and any(reason.startswith(tool.screen_reason) for reason in reasons):
            return tool
    return None


async def blocked_login_tools(
    sessions: async_sessionmaker[AsyncSession],
    clock: Clock,
    settings: LoginSettings,
    tools: Registry[LoginTool] = login_tools,
) -> list[str]:
    """Tools with a recent run stopped on their login dialog and no request made since."""
    since = clock.now() - timedelta(seconds=settings.blocked_run_window_seconds)
    async with sessions() as db:
        runs = list(await db.scalars(select(Run).where(Run.finished_at >= since)))
        rows = await db.execute(
            select(LoginRequest.tool, func.max(LoginRequest.created_at)).group_by(LoginRequest.tool)
        )
        latest = {tool: created for tool, created in rows}
    found: list[str] = []
    for run in runs:
        tool = login_tool_of(run, tools)
        if tool is None or tool.name in found or run.finished_at is None:
            continue
        # A run that ended before the last request for its tool is already answered by it.
        asked = latest.get(tool.name)
        if asked is not None and ensure_utc(run.finished_at) <= ensure_utc(asked):
            continue
        found.append(tool.name)
    return found


async def login_pass(
    sessions: async_sessionmaker[AsyncSession],
    clock: Clock,
    service: LoginService,
    *,
    settings: LoginSettings | None = None,
) -> int:
    """One pass: ask for the blocked tools' logins, then re-check; returns requests started."""
    settings = settings or get_login_settings()
    started = 0
    for name in await blocked_login_tools(sessions, clock, settings):
        outcome = await service.request(name, DEFAULT_ACCOUNT)
        started += int(outcome.created)
    await service.recheck_pending()
    return started
