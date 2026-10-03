"""Voice actions: decide an approval and order a task, answered in speakable text."""

from labhq.callcenter.actions.decide import CONFIRMATION, DECIDER, decide
from labhq.callcenter.actions.order import order

__all__ = ["CONFIRMATION", "DECIDER", "decide", "order"]
