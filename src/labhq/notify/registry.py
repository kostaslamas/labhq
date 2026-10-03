"""`kind -> factory`. A new notifier is a new registration, never a dispatcher edit."""

from collections.abc import Callable
from pathlib import Path

import httpx

from labhq.approvals.registry import Registry
from labhq.notify.base import Notifier, NotifyError
from labhq.notify.ntfy import NtfyNotifier
from labhq.notify.settings import NotifySettings
from labhq.notify.telegram import TelegramNotifier
from labhq.notify.topic import load_or_create_topic

type NotifierFactory = Callable[[NotifySettings, httpx.AsyncClient, Path], Notifier]


def _ntfy(settings: NotifySettings, client: httpx.AsyncClient, data_dir: Path) -> Notifier:
    topic = settings.ntfy_topic or load_or_create_topic(data_dir)
    return NtfyNotifier(
        client, server=settings.ntfy_server, topic=topic, priority=settings.ntfy_priority
    )


def _telegram(settings: NotifySettings, client: httpx.AsyncClient, data_dir: Path) -> Notifier:
    if settings.telegram_token is None or not settings.telegram_chat_id:
        raise NotifyError("telegram needs LABHQ_NOTIFY_TELEGRAM_TOKEN and _TELEGRAM_CHAT_ID")
    return TelegramNotifier(
        client, token=settings.telegram_token.get_secret_value(), chat_id=settings.telegram_chat_id
    )


notifiers: Registry[NotifierFactory] = Registry("notifier")
notifiers.register("ntfy", _ntfy)
notifiers.register("telegram", _telegram)


def build_notifier(
    settings: NotifySettings,
    client: httpx.AsyncClient,
    data_dir: Path,
    *,
    registry: Registry[NotifierFactory] = notifiers,
) -> Notifier:
    return registry.get(settings.kind)(settings, client, data_dir)
