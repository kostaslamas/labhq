"""Step: which folder holds the owner's projects, so the session scan looks nowhere else."""

import asyncio
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from labhq.db import create_engine, session_factory
from labhq.inventory.roots import RootError, add_root, effective_scope, suggestion
from labhq.inventory.settings import get_inventory_settings
from labhq.onboard.base import Detection, ManualAction, OnboardContext, Outcome, StepError

QUESTION = "Which folder holds your projects? (leave empty to skip)"
ATTEMPTS = 3


async def _count_roots(context: OnboardContext) -> int:
    engine = create_engine(context.settings.resolved_database_url)
    try:
        async with session_factory(engine)() as db:
            return len((await effective_scope(db, get_inventory_settings())).roots)
    finally:
        await engine.dispose()


async def _add(context: OnboardContext, raw: str) -> Path:
    engine = create_engine(context.settings.resolved_database_url)
    try:
        async with session_factory(engine)() as db:
            checked = await add_root(db, context.clock, raw)
            await db.commit()
            return checked.path
    finally:
        await engine.dispose()


class SessionScopeStep:
    name = "session scope"
    required = False

    def detect(self, context: OnboardContext) -> Detection:
        try:
            count = asyncio.run(_count_roots(context))
        except SQLAlchemyError:
            count = 0
        if count:
            return Detection(True, f"the session scan looks in {count} folder(s)")
        return Detection(False, "no scope set: the session scan is machine-wide")

    def manual(self, context: OnboardContext, detection: Detection) -> ManualAction | None:
        return None

    def automate(self, context: OnboardContext) -> None:
        """Ask once, pre-filled with a suggestion; an empty answer, or no terminal, skips."""
        if context.ask is None or self.detect(context).present:
            return
        proposed = suggestion(get_inventory_settings())
        for _ in range(ATTEMPTS):
            answer = context.ask(QUESTION, proposed or "").strip()
            if not answer:
                return
            try:
                path = asyncio.run(_add(context, answer))
            except RootError as error:
                context.say(f"session scope: {error}")
                continue
            except SQLAlchemyError as failure:
                raise StepError(f"cannot keep the scan folder: {failure}") from failure
            context.say(f"session scope: searching {path}")
            return

    def verify(self, context: OnboardContext) -> Outcome:
        if self.detect(context).present:
            return Outcome("the session scan stays inside the folders you chose")
        return Outcome(
            "no scope set, so the session scan is machine-wide; "
            "`labhq sessions roots add <folder>` narrows it"
        )
