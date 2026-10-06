"""Scheduler: wakeups from five sources, coalescing, concurrency, checkout, timeouts, reaper."""

from labhq.scheduler.checkout import checkout, release
from labhq.scheduler.dispatch import Dispatch, Verdict, dispatch_one
from labhq.scheduler.reaper import reap_stale_runs
from labhq.scheduler.scheduler import Scheduler, TickReport
from labhq.scheduler.settings import AgentLimits, SchedulerSettings, get_scheduler_settings
from labhq.scheduler.sources import (
    InvalidWakeupError,
    PointerHandler,
    SourceHandler,
    SourceRegistry,
    TemplateHandler,
    UnknownSourceError,
    default_sources,
)
from labhq.scheduler.termination import (
    PosixProcessGroupTerminator,
    ProcessTerminator,
    TerminatorRegistry,
    UnsupportedPlatformError,
    WindowsTaskkillTerminator,
    default_terminators,
)
from labhq.scheduler.wakeups import EnqueueResult, Outcome, Wakeup, enqueue

__all__ = [
    "AgentLimits",
    "Dispatch",
    "EnqueueResult",
    "InvalidWakeupError",
    "Outcome",
    "PointerHandler",
    "PosixProcessGroupTerminator",
    "ProcessTerminator",
    "Scheduler",
    "SchedulerSettings",
    "SourceHandler",
    "SourceRegistry",
    "TemplateHandler",
    "TerminatorRegistry",
    "TickReport",
    "UnknownSourceError",
    "UnsupportedPlatformError",
    "Verdict",
    "Wakeup",
    "WindowsTaskkillTerminator",
    "checkout",
    "default_sources",
    "default_terminators",
    "dispatch_one",
    "enqueue",
    "get_scheduler_settings",
    "reap_stale_runs",
    "release",
]
