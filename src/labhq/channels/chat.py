"""A chat service (Discord, Slack) used as a notification channel: one thread per message."""

from labhq.chat import ChatAdapter, Persona
from labhq.notify.base import Message, NotifyError

CHANNEL_KEY = "notifications"
CHANNEL_NAME = "labhq-notifications"
PERSONA = Persona("labhq")


class ChatNotifier:
    def __init__(self, adapter: ChatAdapter) -> None:
        self._adapter = adapter

    async def send(self, message: Message) -> None:
        text = message.body if message.click_url is None else f"{message.body}\n{message.click_url}"
        try:
            channel = await self._adapter.ensure_channel(CHANNEL_KEY, CHANNEL_NAME)
            thread = await self._adapter.open_thread(channel, message.title)
            await self._adapter.post(thread, PERSONA, text)
        except Exception as error:
            # Only the type: a service's error text may carry a URL or credential.
            raise NotifyError(
                f"the chat service refused the message ({type(error).__name__})"
            ) from None
        finally:
            await self._adapter.close()
