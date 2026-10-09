"""The CEO's report on a scan: one per project, and the sentence the Call Center speaks."""

from sqlalchemy.ext.asyncio import AsyncSession

from labhq.ceoreports import record_report
from labhq.clock import Clock
from labhq.inventory.model import Inventory, ProjectInventory, SessionInfo, ToolStatus

KIND_LABEL = "session inventory"


def idle_text(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    if seconds < 90:
        return "active now"
    minutes = seconds / 60
    if minutes < 90:
        return f"idle {minutes:.0f} min"
    hours = minutes / 60
    if hours < 48:
        return f"idle {hours:.0f} h"
    return f"idle {hours / 24:.0f} days"


def git_text(project: ProjectInventory) -> str:
    if not project.has_repo:
        return "no repo"
    git = project.git
    parts = [f"branch {git.branch}" if git.branch else "no commits yet"]
    parts.append(f"{git.dirty_files} dirty files" if git.dirty_files else "clean")
    if git.last_commit_subject and git.last_commit_at:
        parts.append(f"last commit '{git.last_commit_subject}'")
    if git.open_pr:
        parts.append(f"open PR {git.open_pr}")
    return ", ".join(parts)


def session_line(session: SessionInfo, proposal: str, reason: str) -> str:
    ident = session.session_id or "unknown id"
    return (
        f"- {session.tool} {ident}: {session.state.value}, {idle_text(session.idle_seconds)}"
        f" -> {proposal} ({reason})"
    )


def tool_line(status: ToolStatus) -> str:
    login = {True: "logged in", False: "logged out", None: "login unknown"}[status.logged_in]
    account = f" as {status.account}" if status.account else ""
    plan = f", plan {status.plan} ({status.plan_used_percent:g}% used)" if status.plan else ""
    return f"{status.tool}: {login}{account}{plan}"


def project_report(project: ProjectInventory, tools: list[ToolStatus]) -> str:
    used = {session.tool for session in project.sessions}
    lines = [f"Project {project.name} ({project.root}): {git_text(project)}."]
    for session, proposal in zip(project.sessions, project.proposals, strict=True):
        lines.append(session_line(session, proposal.action.value, proposal.reason))
    lines += [f"  {tool_line(t)}" for t in tools if t.tool in used]
    return "\n".join(lines)


def spoken(inventory: Inventory) -> str:
    """A short answer to "what sessions do I have open?"; the full report is in the chat."""
    if not inventory.projects:
        return "I found no agent sessions on this machine."
    parts = []
    for project in inventory.projects:
        live = [s for s in project.sessions if s.pid is not None]
        saved = len(project.sessions) - len(live)
        parts.append(f"{project.name}: {len(live)} open, {saved} saved")
    text = "; ".join(parts)
    if inventory.folders:
        names = ", ".join(f.folder.name for f in inventory.folders)
        text += f". A folder manager could look after {names}."
    return f"{text}."


async def report_to_ceo(
    db: AsyncSession,
    clock: Clock,
    inventory: Inventory,
    tools: list[ToolStatus],
    *,
    ceo_id: int | None,
) -> list[int]:
    """One CEO report per project; the caller commits. Returns the report ids."""
    ids = []
    for project in inventory.projects:
        report = await record_report(
            db, clock, agent_id=ceo_id, text=project_report(project, tools), refs=[]
        )
        ids.append(report.id)
    return ids
