"""A psutil stub, and hosts, rules and samples for health tests."""

from collections.abc import Iterable
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import psutil
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.clock import FakeClock
from labhq.db.enums import HealthRuleAction
from labhq.db.models import HealthRule, HealthSample, Host


class StubPsutil:
    """Fixed readings in place of the real machine; tests change the attributes they need."""

    def __init__(self) -> None:
        self.cpu = 12.5
        self.memory = SimpleNamespace(percent=40.0, available=8 * 1024**3)
        self.load = (0.5, 0.25, 0.125)
        self.mounts = {"/": 55.0, "/data": 91.0}
        self.temperatures: dict[str, list[Any]] = {
            "coretemp": [SimpleNamespace(label="Package id 0", current=48.0)],
        }

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(psutil, "cpu_percent", lambda interval=None: self.cpu)
        monkeypatch.setattr(psutil, "virtual_memory", lambda: self.memory)
        monkeypatch.setattr(psutil, "getloadavg", lambda: self.load)
        monkeypatch.setattr(
            psutil,
            "disk_partitions",
            lambda all=False: [SimpleNamespace(mountpoint=mount) for mount in self.mounts],
        )
        monkeypatch.setattr(
            psutil, "disk_usage", lambda mount: SimpleNamespace(percent=self.mounts[mount])
        )
        monkeypatch.setattr(
            psutil, "sensors_temperatures", lambda: self.temperatures, raising=False
        )


async def add_host(session: AsyncSession, clock: FakeClock, name: str = "box") -> Host:
    now = clock.now()
    host = Host(name=name, created_at=now, updated_at=now)
    session.add(host)
    await session.flush()
    return host


async def add_rule(
    session: AsyncSession,
    clock: FakeClock,
    *,
    params: dict[str, Any],
    rule_type: str = "threshold",
    enabled: bool = True,
    host: Host | None = None,
    action: HealthRuleAction = HealthRuleAction.NOTIFY,
) -> HealthRule:
    now = clock.now()
    rule = HealthRule(
        type=rule_type,
        name=f"{rule_type} rule",
        params=params,
        action=action,
        host_id=host.id if host else None,
        reason="Test rule",
        created_by="tests",
        enabled=enabled,
        created_at=now,
        updated_at=now,
    )
    session.add(rule)
    await session.flush()
    return rule


async def add_samples(
    session: AsyncSession,
    host: Host,
    metric: str,
    points: Iterable[tuple[datetime, float]],
    subject: str | None = None,
) -> None:
    session.add_all(
        HealthSample(host_id=host.id, metric=metric, subject=subject, value=value, sampled_at=at)
        for at, value in points
    )
    await session.flush()
