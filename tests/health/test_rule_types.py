"""Each new rule type opens an incident for a violating series and none for a healthy one."""

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.clock import FakeClock
from labhq.db.models import Incident
from labhq.health.incidents import evaluate_rules
from labhq.health.rule_types import http_probe
from labhq.health.rules import registry
from tests.health.factories import add_host, add_rule, add_samples

MINUTE = timedelta(minutes=1)
HOUR = timedelta(hours=1)
NEW_TYPES = ("service_active", "http", "cert_expiry", "log_pattern", "trend")

# (minutes before now, value); the evaluation runs at the clock's now.
Series = list[tuple[float, float]]


@dataclass(frozen=True)
class Case:
    rule_type: str
    params: dict[str, Any]
    metric: str = ""
    subject: str | None = None
    violating: Series = field(default_factory=list)
    healthy: Series = field(default_factory=list)


def _rising(per_hour: float, start: float) -> Series:
    return [(60.0 * hours, start - per_hour * hours) for hours in range(24, -1, -4)]


CASES = [
    Case(
        "service_active",
        {"name": "nginx.service"},
        "service.active",
        "nginx.service",
        violating=[(10, 1), (5, 1), (0, 0)],
        healthy=[(10, 0), (5, 1), (0, 1)],
    ),
    Case(
        "service_active",
        {"kind": "container"},
        "container.running",
        "postgres",
        violating=[(0, 0)],
        healthy=[(0, 1)],
    ),
    Case(
        "cert_expiry",
        {"days": 14},
        "cert.days_left",
        "example.org:443",
        violating=[(60, 13.0), (0, 12.9)],
        healthy=[(60, 40.0), (0, 39.9)],
    ),
    Case(
        "log_pattern",
        {"count": 10, "window_seconds": 3600},
        "journal.errors",
        violating=[(50, 4), (30, 4), (10, 4)],
        # Old errors outside the window do not count.
        healthy=[(120, 50), (30, 3), (10, 3)],
    ),
    Case(
        "log_pattern",
        {"pattern": "Out of memory", "count": 0, "window_seconds": 600},
        "journal.matches",
        "Out of memory",
        violating=[(5, 1)],
        healthy=[(5, 0), (0, 0)],
    ),
    Case(
        "trend",
        {"metric": "disk.percent", "limit": 100, "within_days": 5, "subject": "/"},
        "disk.percent",
        "/",
        # One point a day: 100% in about two days.
        violating=_rising(per_hour=1.0, start=52.0),
        healthy=[(60.0 * hours, 52.0) for hours in range(24, -1, -4)],
    ),
]


def _ids(cases: list[Case]) -> Iterator[str]:
    for case in cases:
        yield f"{case.rule_type}:{case.metric}"


def test_new_types_are_registered() -> None:
    assert set(NEW_TYPES) <= registry.types()


@pytest.mark.parametrize("case", CASES, ids=list(_ids(CASES)))
@pytest.mark.parametrize("violating", [True, False], ids=["violating", "healthy"])
async def test_a_series_opens_an_incident_only_when_it_violates(
    session: AsyncSession, clock: FakeClock, case: Case, violating: bool
) -> None:
    host = await add_host(session, clock)
    rule = await add_rule(session, clock, params=case.params, rule_type=case.rule_type)
    series = case.violating if violating else case.healthy
    points = [(clock.now() - minutes * MINUTE, value) for minutes, value in series]
    await add_samples(session, host, case.metric, points, subject=case.subject)

    changes = await evaluate_rules(session, clock)

    incidents = (await session.scalars(select(Incident))).all()
    assert len(incidents) == (1 if violating else 0)
    assert len(changes) == len(incidents)
    if violating:
        assert incidents[0].rule_id == rule.id
        assert incidents[0].details["metric"] == case.metric


class StubProbe:
    def __init__(self, *, connects: bool = True, status: int | None = 200) -> None:
        self._connects = connects
        self._status = status
        self.calls: list[tuple[str, ...]] = []

    async def connects(self, address: str, port: int, timeout: float) -> bool:
        self.calls.append(("connect", address, str(port)))
        return self._connects

    async def status(self, url: str, timeout: float) -> int | None:
        self.calls.append(("get", url))
        return self._status


@pytest.mark.parametrize(
    ("params", "probe", "violated"),
    [
        ({"port": 5432}, StubProbe(connects=True), False),
        ({"port": 5432}, StubProbe(connects=False), True),
        ({"url": "https://example.org/health"}, StubProbe(status=200), False),
        ({"url": "https://example.org/health"}, StubProbe(status=503), True),
        ({"url": "https://example.org/health"}, StubProbe(status=None), True),
        ({"url": "https://example.org/", "expected_status": 401}, StubProbe(status=401), False),
    ],
)
async def test_http_probes_a_port_or_a_url(
    session: AsyncSession,
    clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
    params: dict[str, Any],
    probe: StubProbe,
    violated: bool,
) -> None:
    monkeypatch.setattr(http_probe, "probe", probe)
    host = await add_host(session, clock)
    host.address = "10.0.0.7"
    await add_rule(session, clock, params=params, rule_type="http")

    await evaluate_rules(session, clock)

    incidents = (await session.scalars(select(Incident))).all()
    assert len(incidents) == (1 if violated else 0)
    if "port" in params:
        assert probe.calls == [("connect", "10.0.0.7", "5432")]


async def test_http_probes_loopback_for_the_local_host(
    session: AsyncSession, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    probe = StubProbe()
    monkeypatch.setattr(http_probe, "probe", probe)
    host = await add_host(session, clock)
    host.is_local = True
    await add_rule(session, clock, params={"port": 22}, rule_type="http")
    await evaluate_rules(session, clock)
    assert probe.calls == [("connect", "127.0.0.1", "22")]


@pytest.mark.parametrize(
    ("rule_type", "params"),
    [
        ("service_active", {"kind": "vm"}),
        ("http", {}),
        ("http", {"port": 80, "url": "https://example.org"}),
        ("http", {"port": 70000}),
        ("cert_expiry", {"days": 0}),
        ("log_pattern", {"count": -1}),
        ("trend", {"metric": "disk.percent", "limit": 100}),
        ("trend", {"metric": "disk.percent", "limit": 100, "within_days": 5, "fix": "rm"}),
    ],
)
def test_malformed_params_are_rejected(rule_type: str, params: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        registry.validate_params(rule_type, params)


def test_validated_params_carry_their_defaults() -> None:
    stored = registry.validate_params("cert_expiry", {"days": 7})
    assert stored == {"days": 7.0, "subject": None}
    assert (
        HOUR.total_seconds()
        == registry.validate_params("log_pattern", {"count": 1})["window_seconds"]
    )
