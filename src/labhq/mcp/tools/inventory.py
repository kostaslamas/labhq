"""Session inventory tools: what sessions are open, and an analysis of one project on request."""

import asyncio

from mcp.types import ToolAnnotations

from labhq.api.public_url import current_public_url
from labhq.db import create_engine, session_factory
from labhq.inventory import (
    copy,
    register,  # noqa: F401  (registers the approval executors)
)
from labhq.inventory.analysis import Analyses, AnalysisError
from labhq.inventory.chooser import NoRunnerError
from labhq.inventory.scoped import scanner_for
from labhq.inventory.service import scan_and_report
from labhq.mcp.tools.registry import ToolSpec, default_registry
from labhq.mcp.tools.runtime import CLOCK, tool_session
from labhq.settings import Settings


async def sessions_tool() -> str:
    async with tool_session() as db:
        result = await scan_and_report(db, CLOCK)
        await db.commit()
        return result.text


# The CEO tab opens with the "Where labhq looks for sessions" panel in view.
SCOPE_PATH = "/ceo?panel=scan"


async def scan_scope_tool(folder: str | None = None) -> str:
    """Say where the scan looks and how many sessions it left out. It never changes the list."""
    async with tool_session() as db:
        scanner = await scanner_for(db, CLOCK)
    found = await asyncio.to_thread(scanner.scan)
    if found.roots:
        roots = ", ".join(str(root) for root in found.roots)
        lines = [copy.SCOPE_ROOTS.format(roots=roots, left=found.left_out)]
    else:
        lines = [copy.SCOPE_WIDE]
    if folder and folder.strip():
        lines.append(copy.SCOPE_ASKED.format(folder=folder.strip()))
    base = current_public_url()
    lines.append(copy.SCOPE_LINK.format(link=f"{base}{SCOPE_PATH}") if base else copy.SCOPE_NO_LINK)
    return " ".join(lines)


async def analyse_tool(project: str) -> str:
    engine = create_engine(Settings().resolved_database_url)
    try:
        try:
            request = await Analyses(session_factory(engine), clock=CLOCK).request(project)
        except (AnalysisError, NoRunnerError) as error:
            return f"I cannot analyse that: {error}."
        return request.text
    finally:
        await engine.dispose()


default_registry.register(
    ToolSpec(
        "sessions",
        "Scan this machine for coding-agent sessions (running and saved, every supported "
        "tool), group them by project and report them to the CEO. Free: no model is called "
        "and no conversation is read. Read the answer aloud as it is.",
        ToolAnnotations(readOnlyHint=False, destructiveHint=False),
        sessions_tool,
    )
)
default_registry.register(
    ToolSpec(
        "analyse",
        "Prepare the analysis of ONE project's agent sessions, when the owner names that "
        "project. It starts nothing: it returns the estimated cost, who would run it and an "
        "approval reference. Read it aloud and wait for the owner's clear yes; only then "
        "call decide with that reference. Never offer to analyse every project at once.",
        ToolAnnotations(readOnlyHint=False, destructiveHint=False),
        analyse_tool,
    )
)
default_registry.register(
    ToolSpec(
        "session_scope",
        "Say which folders the session scan looks in and how many sessions it left out, and "
        "give the link to the CEO tab, whose scan panel is where the owner changes the "
        "list with a confirmation. Use it when the owner asks to search another folder, for "
        "example "
        "'ψάξε και στο ~/Developer': pass that folder as `folder`. It changes nothing by "
        "itself. Read the answer aloud as it is.",
        ToolAnnotations(readOnlyHint=True),
        scan_scope_tool,
    )
)
