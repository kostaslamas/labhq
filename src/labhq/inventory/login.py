"""Login and plan state per tool, from the tool's own status command and labhq's usage readings.

The status command is the tool's: labhq runs it and looks at its exit code and, for the
account, at an email address in its output. No credential file is opened (ADR 0001) and the
output is not kept. A tool without a status command is reported as unknown (`None`), never as
logged in. Plan room comes from `labhq.usage` readings the runs already recorded.
"""

import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from labhq.adapters.tmux import AgentKind, AgentKinds
from labhq.clock import Clock
from labhq.inventory.model import ToolStatus
from labhq.inventory.settings import InventorySettings
from labhq.usage import check_kind

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")

# Runs a status command: (exit code, output), or None when it cannot run.
StatusRunner = Callable[[tuple[str, ...], float], tuple[int, str] | None]
Which = Callable[[str], str | None]


def run_status(argv: tuple[str, ...], timeout: float) -> tuple[int, str] | None:
    try:
        result = subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            stdin=subprocess.DEVNULL,
            cwd=Path.cwd(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.returncode, f"{result.stdout}\n{result.stderr}"


def login_of(kind: AgentKind, run: StatusRunner, timeout: float) -> tuple[bool | None, str | None]:
    """(logged in or None when unknown, the account's email if the output shows one)."""
    if kind.login_status is None:
        return None, None
    outcome = run(kind.login_status, timeout)
    if outcome is None:
        return None, None
    code, output = outcome
    match = EMAIL.search(output)
    out = kind.logged_out_pattern is not None and re.search(
        kind.logged_out_pattern, output, re.IGNORECASE
    )
    return (code == 0 and not out), (match.group() if match else None)


async def tool_statuses(
    db: AsyncSession,
    kinds: AgentKinds,
    clock: Clock,
    settings: InventorySettings,
    *,
    run: StatusRunner = run_status,
    which: Which = shutil.which,
) -> list[ToolStatus]:
    statuses = []
    for name in kinds.names():
        kind = kinds.get(name)
        if which(kind.start[0]) is None:
            continue
        logged_in, account = login_of(kind, run, settings.command_timeout_seconds)
        plan = await check_kind(db, name, clock)
        used = max((w.used_percent for w in plan.windows), default=None)
        statuses.append(
            ToolStatus(
                tool=name,
                logged_in=logged_in,
                account=account,
                plan=str(plan.decision) if plan.windows else None,
                plan_used_percent=used,
            )
        )
    return statuses
