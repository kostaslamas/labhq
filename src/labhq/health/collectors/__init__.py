"""Collection per host kind: probes as read-only commands, run locally or over SSH."""

from labhq.health.collectors.commands import (
    CommandProbe,
    CommandResult,
    CommandRunner,
    LocalRunner,
    ProbeContext,
    ProbeError,
    run_probes,
)
from labhq.health.collectors.local import LocalCollector
from labhq.health.collectors.registry import (
    LOCAL_KIND,
    SSH_KIND,
    CollectionSettings,
    Collector,
    CollectorRegistry,
    HostTarget,
    UnknownHostKindError,
)
from labhq.health.collectors.remote import REMOTE_PROBES, SshCollector

default_collectors = CollectorRegistry()
default_collectors.register(LOCAL_KIND, LocalCollector())
default_collectors.register(SSH_KIND, SshCollector())

__all__ = [
    "LOCAL_KIND",
    "REMOTE_PROBES",
    "SSH_KIND",
    "CollectionSettings",
    "Collector",
    "CollectorRegistry",
    "CommandProbe",
    "CommandResult",
    "CommandRunner",
    "HostTarget",
    "LocalCollector",
    "LocalRunner",
    "ProbeContext",
    "ProbeError",
    "SshCollector",
    "UnknownHostKindError",
    "default_collectors",
    "run_probes",
]
