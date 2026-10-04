"""`kind -> factory`. A new notifier is a new registration, never a dispatcher edit."""

from collections.abc import Callable
from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.approvals.registry import Registry
from labhq.notify.base import Notifier, NotifyError
from labhq.notify.ntfy import NtfyNotifier
from labhq.notify.settings import NotifySettings
from labhq.notify.telegram import TelegramNotifier
from labhq.notify.topic import load_or_create_topic
from labhq.notify.vapid import load_or_create_vapid
from labhq.notify.webpush import WebPushNotifier

type Sessions = async_sessionmaker[AsyncSession]
# The session factory is for notifiers that read the database (Web Push subscriptions).
type NotifierFactory = Callable[
    [NotifySettings, httpx.AsyncClient, Path, Sessions | None], Notifier
]


def _ntfy(
    settings: NotifySettings, client: httpx.AsyncClient, data_dir: Path, sessions: Sessions | None
) -> Notifier:
    topic = settings.ntfy_topic or load_or_create_topic(data_dir)
    return NtfyNotifier(
        client, server=settings.ntfy_server, topic=topic, priority=settings.ntfy_priority
    )


def _telegram(
    settings: NotifySettings, client: httpx.AsyncClient, data_dir: Path, sessions: Sessions | None
) -> Notifier:
    if settings.telegram_token is None or not settings.telegram_chat_id:
        raise NotifyError("telegram needs LABHQ_NOTIFY_TELEGRAM_TOKEN and _TELEGRAM_CHAT_ID")
    return TelegramNotifier(
        client, token=settings.telegram_token.get_secret_value(), chat_id=settings.telegram_chat_id
    )


def _webpush(
    settings: NotifySettings, client: httpx.AsyncClient, data_dir: Path, sessions: Sessions | None
) -> Notifier:
    if sessions is None:
        raise NotifyError("webpush needs the database to read subscriptions from")
    return WebPushNotifier(
        sessions,
        load_or_create_vapid(data_dir),
        subject=settings.webpush_subject,
        ttl_seconds=settings.webpush_ttl_seconds,
    )


notifiers: Registry[NotifierFactory] = Registry("notifier")
notifiers.register("webpush", _webpush)
notifiers.register("ntfy", _ntfy)
notifiers.register("telegram", _telegram)


def build_notifier(
    settings: NotifySettings,
    client: httpx.AsyncClient,
    data_dir: Path,
    *,
    sessions: Sessions | None = None,
    registry: Registry[NotifierFactory] = notifiers,
) -> Notifier:
    return registry.get(settings.kind)(settings, client, data_dir, sessions)
