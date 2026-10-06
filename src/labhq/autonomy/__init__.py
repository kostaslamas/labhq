"""The CEO acting on its own: heartbeat, scheduled meetings and the global autonomy switch."""

from labhq.autonomy.settings import Autonomy, AutonomySettings, get_autonomy_settings
from labhq.autonomy.state import get_autonomy, set_autonomy

__all__ = [
    "Autonomy",
    "AutonomySettings",
    "get_autonomy",
    "get_autonomy_settings",
    "set_autonomy",
]
