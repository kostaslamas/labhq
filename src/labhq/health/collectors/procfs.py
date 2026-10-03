"""CPU, memory, load and disks of a remote Linux host, from `/proc` and `df -P`.

The local host reads the same metrics through psutil; these probes give a remote host the
same names and subjects, so one rule watches both.
"""

from labhq.health.collector import Reading
from labhq.health.collectors.commands import Argv, CommandProbe, ProbeContext, ProbeError

# Two snapshots a second apart: /proc/stat alone only gives the average since boot.
_CPU_SCRIPT = "head -n 1 /proc/stat; sleep 1; head -n 1 /proc/stat"
# user nice system idle iowait irq softirq steal; guest time is already inside user.
_CPU_FIELDS = 8
_IDLE_FIELDS = (3, 4)


def _cpu(_: ProbeContext) -> Argv:
    return ("sh", "-c", _CPU_SCRIPT)


def _cpu_times(line: str) -> tuple[int, int]:
    fields = line.split()
    if not fields or fields[0] != "cpu":
        raise ProbeError(f"not a /proc/stat cpu line: {line!r}")
    values = [int(value) for value in fields[1 : 1 + _CPU_FIELDS]]
    idle = sum(values[index] for index in _IDLE_FIELDS if index < len(values))
    return sum(values), idle


def parse_cpu(output: str, _: ProbeContext) -> list[Reading]:
    lines = [line for line in output.splitlines() if line.strip()]
    if len(lines) != 2:
        raise ProbeError("expected two /proc/stat snapshots")
    (total_before, idle_before), (total_after, idle_after) = map(_cpu_times, lines)
    elapsed = total_after - total_before
    if elapsed <= 0:
        raise ProbeError("no CPU time passed between the snapshots")
    busy = 1.0 - (idle_after - idle_before) / elapsed
    return [Reading("cpu.percent", round(100.0 * busy, 1))]


def _meminfo(_: ProbeContext) -> Argv:
    return ("cat", "/proc/meminfo")


def parse_memory(output: str, _: ProbeContext) -> list[Reading]:
    kibibytes = {}
    for line in output.splitlines():
        key, _colon, rest = line.partition(":")
        fields = rest.split()
        if fields:
            kibibytes[key.strip()] = int(fields[0])
    try:
        total, available = kibibytes["MemTotal"], kibibytes["MemAvailable"]
    except KeyError as missing:
        raise ProbeError(f"/proc/meminfo has no {missing}") from None
    # psutil's formula, so a remote host's percentage means what the local one does.
    percent = 100.0 * (total - available) / total
    return [
        Reading("memory.percent", round(percent, 1)),
        Reading("memory.available_bytes", float(available * 1024)),
    ]


def _loadavg(_: ProbeContext) -> Argv:
    return ("cat", "/proc/loadavg")


def parse_load(output: str, _: ProbeContext) -> list[Reading]:
    fields = output.split()
    if len(fields) < 3:
        raise ProbeError("/proc/loadavg has fewer than three averages")
    names = ("load.1m", "load.5m", "load.15m")
    return [Reading(name, float(value)) for name, value in zip(names, fields, strict=False)]


# Memory-backed and image filesystems: full by design or meaningless as disk usage.
PSEUDO_FILESYSTEMS = frozenset(
    {"tmpfs", "devtmpfs", "udev", "overlay", "squashfs", "none", "shm", "efivarfs"}
)
_DF_COLUMNS = 6


def _df(_: ProbeContext) -> Argv:
    return ("df", "-P", "-k")


def parse_disks(output: str, _: ProbeContext) -> list[Reading]:
    readings = []
    for line in output.splitlines()[1:]:
        fields = line.split()
        if len(fields) < _DF_COLUMNS or fields[0] in PSEUDO_FILESYSTEMS:
            continue
        used, available = int(fields[2]), int(fields[3])
        if used + available == 0:
            continue
        # A mount point may contain spaces; it is everything after the capacity column.
        mount = " ".join(fields[_DF_COLUMNS - 1 :])
        percent = 100.0 * used / (used + available)
        readings.append(Reading("disk.percent", round(percent, 1), mount))
    return readings


PROCFS_PROBES: tuple[CommandProbe, ...] = (
    CommandProbe("cpu", _cpu, parse_cpu),
    CommandProbe("memory", _meminfo, parse_memory),
    CommandProbe("load", _loadavg, parse_load),
    CommandProbe("disks", _df, parse_disks),
)
