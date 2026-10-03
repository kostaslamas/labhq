"""Live updates: a change feed across processes, an in-process broker and `/api/live`."""

# First, and on purpose: `labhq.api.routes` imports the endpoint, which imports `labhq.api`.
# Loading the API package before the endpoint lets either side be imported first.
import labhq.api  # noqa: F401
from labhq.live import topics
from labhq.live.broker import Broker, Change, Subscription, default_broker
from labhq.live.endpoint import attach, live_router
from labhq.live.feed import ChangeFeed, live_feed
from labhq.live.registry import Topic, TopicRegistry, default_topics
from labhq.live.settings import LiveSettings

__all__ = [
    "Broker",
    "Change",
    "ChangeFeed",
    "LiveSettings",
    "Subscription",
    "Topic",
    "TopicRegistry",
    "attach",
    "default_broker",
    "default_topics",
    "live_feed",
    "live_router",
    "topics",
]
