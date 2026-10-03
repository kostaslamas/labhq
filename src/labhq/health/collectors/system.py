"""Probes of a machine's services, containers, disks' SMART state, journal, certificates and
pending updates (plan §2.2). Each is a read-only command and a parser, for every host kind.

The metric names are the ones the rule types of #75 read; the strings are the contract.
"""

from datetime import UTC, datetime

from labhq.health.collector import Reading
from labhq.health.collectors.commands import Argv, CommandProbe, ProbeContext, ProbeError

# systemd's ACTIVE column. A unit that is not listed is not reported.
_UNIT_STATES: dict[str, float] = {
    "active": 1.0,
    "reloading": 1.0,
    "activating": 1.0,
    "deactivating": 0.0,
    "inactive": 0.0,
    "failed": 0.0,
}
_UNIT_SUFFIX = ".service"


def _units(_: ProbeContext) -> Argv:
    return ("systemctl", "list-units", "--type=service", "--no-legend", "--plain", "--no-pager")


def parse_units(output: str, _: ProbeContext) -> list[Reading]:
    readings = []
    for line in output.splitlines():
        fields = line.replace("●", " ").split()
        if len(fields) < 3 or fields[2] not in _UNIT_STATES:
            continue
        name = fields[0].removesuffix(_UNIT_SUFFIX)
        readings.append(Reading("service.active", _UNIT_STATES[fields[2]], name))
    return readings


def _containers(_: ProbeContext) -> Argv:
    return ("docker", "ps", "--all", "--format", "{{.Names}}\t{{.State}}")


def parse_containers(output: str, _: ProbeContext) -> list[Reading]:
    readings = []
    for line in output.splitlines():
        name, _tab, state = line.strip().partition("\t")
        if name and state:
            readings.append(Reading("container.running", float(state == "running"), name))
    return readings


# Without smartctl the probe fails instead of reporting no disks.
_SMART_SCRIPT = """
command -v smartctl >/dev/null 2>&1 || exit 127
for device in $(smartctl --scan | cut -d ' ' -f 1); do
  echo "== $device"
  smartctl -H "$device"
done
exit 0
"""
_SMART_HEALTHY = ("PASSED", "Health Status: OK")
_SMART_FAILING = ("FAILED", "Health Status: FAIL")


def _smart(_: ProbeContext) -> Argv:
    return ("sh", "-c", _SMART_SCRIPT)


def _blocks(output: str) -> dict[str, str]:
    """`== subject` headers and the lines under each."""
    blocks: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in output.splitlines():
        if line.startswith("== "):
            current = blocks.setdefault(line[3:].strip(), [])
        elif current is not None:
            current.append(line)
    return {subject: "\n".join(lines) for subject, lines in blocks.items()}


def parse_smart(output: str, _: ProbeContext) -> list[Reading]:
    readings = []
    for device, text in _blocks(output).items():
        # A device smartctl could not open has no verdict; it is left out, never healthy.
        if any(marker in text for marker in _SMART_FAILING):
            readings.append(Reading("smart.healthy", 0.0, device))
        elif any(marker in text for marker in _SMART_HEALTHY):
            readings.append(Reading("smart.healthy", 1.0, device))
    return readings


def _journal(context: ProbeContext) -> Argv:
    # Whole seconds, since is inclusive and until is not reached: no entry counts twice.
    since = int(context.since.timestamp())
    until = int(context.now.timestamp()) - 1
    return (
        "journalctl",
        "--priority=err",
        f"--since=@{since}",
        f"--until=@{until}",
        "--output=json",
        "--no-pager",
        "--quiet",
    )


def parse_journal(output: str, _: ProbeContext) -> list[Reading]:
    # One JSON object per entry and line, so multi-line messages still count once.
    count = sum(1 for line in output.splitlines() if line.startswith("{"))
    return [Reading("journal.errors", float(count))]


# Targets arrive as positional arguments, so no target is ever parsed as shell syntax.
_CERT_SCRIPT = """
for target in "$@"; do
  echo "== $target"
  case "$target" in
    /*) openssl x509 -noout -enddate -in "$target" 2>&1 ;;
    *) printf '' | openssl s_client -connect "$target" -servername "${target%:*}" 2>/dev/null \
         | openssl x509 -noout -enddate 2>&1 ;;
  esac
done
exit 0
"""
_NOT_AFTER = "notAfter="
_SECONDS_PER_DAY = 86400.0


def _certificates(context: ProbeContext) -> Argv | None:
    if not context.certificates:
        return None
    return ("sh", "-c", _CERT_SCRIPT, "sh", *context.certificates)


def _not_after(text: str) -> datetime | None:
    for line in text.splitlines():
        if line.startswith(_NOT_AFTER):
            # `Jan  1 00:00:00 2027 GMT`: openssl pads the day with a space.
            stamp = " ".join(line.removeprefix(_NOT_AFTER).split())
            return datetime.strptime(stamp, "%b %d %H:%M:%S %Y GMT").replace(tzinfo=UTC)
    return None


def parse_certificates(output: str, context: ProbeContext) -> list[Reading]:
    readings = []
    for target, text in _blocks(output).items():
        expires = _not_after(text)
        if expires is None:
            # An unreachable port or unreadable file costs that certificate only.
            continue
        days = (expires - context.now).total_seconds() / _SECONDS_PER_DAY
        readings.append(Reading("cert.days_left", days, target))
    return readings


# The first line names the package manager, so the parser needs no guess.
_UPDATES_SCRIPT = """
if command -v apt >/dev/null 2>&1; then
  echo '#apt'
  apt list --upgradable 2>/dev/null
elif command -v dnf >/dev/null 2>&1; then
  echo '#dnf'
  dnf -q check-update
  [ "$?" -eq 1 ] && exit 1
else
  exit 127
fi
exit 0
"""


def _count_apt(lines: list[str]) -> int:
    return sum(1 for line in lines if "[upgradable from:" in line)


def _count_dnf(lines: list[str]) -> int:
    # Package lines are `name.arch version repo`; the obsoletes section repeats packages.
    count = 0
    for line in lines:
        if line.startswith("Obsoleting"):
            break
        count += len(line.split()) == 3
    return count


_UPDATE_COUNTERS = {"#apt": _count_apt, "#dnf": _count_dnf}


def _updates(_: ProbeContext) -> Argv:
    return ("sh", "-c", _UPDATES_SCRIPT)


def parse_updates(output: str, _: ProbeContext) -> list[Reading]:
    lines = output.splitlines()
    counter = _UPDATE_COUNTERS.get(lines[0].strip() if lines else "")
    if counter is None:
        raise ProbeError("no package manager named in the output")
    return [Reading("updates.pending", float(counter(lines[1:])))]


SYSTEM_PROBES: tuple[CommandProbe, ...] = (
    CommandProbe("services", _units, parse_units),
    CommandProbe("containers", _containers, parse_containers),
    CommandProbe("smart", _smart, parse_smart),
    CommandProbe("journal", _journal, parse_journal),
    CommandProbe("certificates", _certificates, parse_certificates),
    CommandProbe("updates", _updates, parse_updates),
)
