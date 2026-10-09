"""Session inventory tools: what sessions are open, and an analysis of one project on request."""

from mcp.types import ToolAnnotations

from labhq.db import create_engine, session_factory
from labhq.inventory import register  # noqa: F401  (registers the approval executors)
from labhq.inventory.analysis import Analyses, AnalysisError
from labhq.inventory.chooser import NoRunnerError
from labhq.inventory.service import scan_and_report
from labhq.mcp.tools.registry import ToolSpec, default_registry
from labhq.mcp.tools.runtime import CLOCK, tool_session
from labhq.settings import Settings


async def sessions_tool() -> str:
    async with tool_session() as db:
        result = await scan_and_report(db, CLOCK)
        await db.commit()
        return result.text


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
