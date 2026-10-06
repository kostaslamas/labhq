"""Server memory as the scheduler sees it, and the run cap that follows from it."""

from collections.abc import Callable
from dataclasses import dataclass

import psutil

# One CLI agent takes hundreds of MB; this is the headroom each admitted run is budgeted.
BYTES_PER_RUN = int(1.5 * 1024**3)
MIN_DEFAULT_CAP = 1
MAX_DEFAULT_CAP = 8


@dataclass(frozen=True)
class MemoryReading:
    total_bytes: int
    available_bytes: int

    @property
    def free_percent(self) -> float:
        if self.total_bytes <= 0:
            return 100.0
        return 100.0 * self.available_bytes / self.total_bytes


# Injectable, like the health collector's probes: tests never read the real machine.
MemoryMeter = Callable[[], MemoryReading]


def system_memory() -> MemoryReading:
    memory = psutil.virtual_memory()
    return MemoryReading(total_bytes=int(memory.total), available_bytes=int(memory.available))


def default_max_running(total_bytes: int) -> int:
    """About one run per 1.5 GB of RAM, at least 1 and at most 8."""
    return max(MIN_DEFAULT_CAP, min(MAX_DEFAULT_CAP, total_bytes // BYTES_PER_RUN))
