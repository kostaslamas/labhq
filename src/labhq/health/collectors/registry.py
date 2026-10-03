"""Collectors per host kind, as a registry: `kind -> collector`. A new kind is a registration."""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

from pydantic_settings import BaseSettings, SettingsConfigDict

from labhq.db.models import Host
from labhq.health.collector import Reading
from labhq.health.collectors.commands import ProbeContext

LOCAL_KIND = "local"
SSH_KIND = "ssh"


@dataclass(frozen=True)
class HostTarget:
    """What a collector needs of a `hosts` row, read before any connection is opened."""

    id: int
    name: str
    is_local: bool
    address: str | None = None
    ssh_user: str | None = None

    @classmethod
    def of(cls, host: Host) -> "HostTarget":
        return cls(host.id, host.name, host.is_local, host.address, host.ssh_user)

    @property
    def kind(self) -> str:
        # The row picks its kind through `is_local`; every other host is reached over SSH.
        return LOCAL_KIND if self.is_local else SSH_KIND


class CollectionSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LABHQ_HEALTH_", extra="ignore")

    # Host name -> certificates to watch on it, `host:port` or a path, as JSON in the env.
    certificates: dict[str, list[str]] = {}

    def certificates_for(self, host: str) -> tuple[str, ...]:
        return tuple(self.certificates.get(host, ()))


class Collector(Protocol):
    async def read(self, host: HostTarget, context: ProbeContext) -> list[Reading]:
        """Every metric the host yields now; raise only when the host itself is unreachable."""
        ...


class UnknownHostKindError(LookupError):
    pass


class CollectorRegistry:
    def __init__(self) -> None:
        self._collectors: dict[str, Collector] = {}

    def register(self, kind: str, collector: Collector, *, replace: bool = False) -> None:
        if kind in self._collectors and not replace:
            raise ValueError(f"host kind already registered: {kind}")
        self._collectors[kind] = collector

    def get(self, kind: str) -> Collector:
        try:
            return self._collectors[kind]
        except KeyError:
            raise UnknownHostKindError(kind) from None

    def __iter__(self) -> Iterator[str]:
        return iter(sorted(self._collectors))

    def copy(self) -> "CollectorRegistry":
        clone = CollectorRegistry()
        clone._collectors = dict(self._collectors)
        return clone
