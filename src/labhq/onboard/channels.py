"""Step: at least one notification channel exists, and its test message arrives.

Where no channel is recorded yet, the notifier the environment configures (ntfy by default)
becomes the first one, so it can be tested, switched off and removed on the Channels page
like any other. More are added later with `labhq channels add` or on that page.
"""

import asyncio

import httpx
from sqlalchemy.exc import SQLAlchemyError

from labhq.channels import ChannelConfigError, ChannelRuntime, list_channels
from labhq.channels.setup import create_and_test
from labhq.db import create_engine, session_factory
from labhq.notify import NotifySettings
from labhq.notify.topic import load_or_create_topic
from labhq.onboard.base import Detection, ManualAction, OnboardContext, Outcome, StepError

FIRST_NAME = "first"
OFFER = "Record your notifier as the first notification channel?"
MORE = "Add more with `labhq channels add`, or on the Channels page of the web UI."


def first_channel_values(settings: NotifySettings, context: OnboardContext) -> dict[str, str]:
    """The settings of the environment's notifier, in the shape its channel kind takes."""
    if settings.kind == "telegram" and settings.telegram_token and settings.telegram_chat_id:
        return {
            "token": settings.telegram_token.get_secret_value(),
            "chat_id": settings.telegram_chat_id,
        }
    topic = settings.ntfy_topic or load_or_create_topic(context.settings.data_dir)
    return {"server": settings.ntfy_server, "topic": topic}


class ChannelsStep:
    name = "channels"
    required = False

    def detect(self, context: OnboardContext) -> Detection:
        try:
            count = asyncio.run(self._count(context))
        except SQLAlchemyError:
            return Detection(False, "no channel is recorded yet")
        if count:
            return Detection(True, f"{count} notification channel(s) enabled")
        return Detection(False, "no channel is recorded yet")

    def manual(self, context: OnboardContext, detection: Detection) -> ManualAction | None:
        return None

    def automate(self, context: OnboardContext) -> None:
        if self.detect(context).present:
            return
        if context.confirm is not None and not context.confirm(OFFER):
            context.say(MORE)
            return
        settings = NotifySettings()
        kind = "telegram" if settings.kind == "telegram" else "ntfy"
        error = asyncio.run(self._add(context, settings, kind))
        if error is not None:
            raise StepError(f"the first channel was added, but its test failed ({error})")

    def verify(self, context: OnboardContext) -> Outcome:
        detection = self.detect(context)
        if not detection.present:
            raise StepError("no notification channel is set up; " + MORE)
        error = asyncio.run(self._test_all(context))
        if error is not None:
            raise StepError(f"a channel's test message was not accepted ({error})")
        return Outcome(f"{detection.detail}; every test message arrived. {MORE}")

    @staticmethod
    async def _count(context: OnboardContext) -> int:
        engine = create_engine(context.settings.resolved_database_url)
        try:
            async with session_factory(engine)() as db:
                return len(await list_channels(db, enabled_only=True))
        finally:
            await engine.dispose()

    @staticmethod
    async def _add(context: OnboardContext, settings: NotifySettings, kind: str) -> str | None:
        engine = create_engine(context.settings.resolved_database_url)
        sessions = session_factory(engine)
        try:
            async with httpx.AsyncClient(timeout=context.onboard.http_timeout_seconds) as client:
                runtime = ChannelRuntime(
                    sessions, client, context.settings.data_dir, context.clock, settings
                )
                try:
                    _, error = await create_and_test(
                        sessions,
                        runtime,
                        context.settings.data_dir,
                        context.clock,
                        kind=kind,
                        name=FIRST_NAME,
                        values=first_channel_values(settings, context),
                    )
                except ChannelConfigError as refusal:
                    raise StepError(str(refusal)) from None
                return error
        finally:
            await engine.dispose()

    @staticmethod
    async def _test_all(context: OnboardContext) -> str | None:
        engine = create_engine(context.settings.resolved_database_url)
        sessions = session_factory(engine)
        try:
            async with httpx.AsyncClient(timeout=context.onboard.http_timeout_seconds) as client:
                runtime = ChannelRuntime(
                    sessions, client, context.settings.data_dir, context.clock, NotifySettings()
                )
                async with sessions() as db:
                    rows = await list_channels(db, enabled_only=True)
                for row in rows:
                    # A channel just added was tested by `create_and_test`; once is enough.
                    if row.last_test_ok:
                        continue
                    if (error := await runtime.test(row.id)) is not None:
                        return f"{row.name}: {error}"
                return None
        finally:
            await engine.dispose()
