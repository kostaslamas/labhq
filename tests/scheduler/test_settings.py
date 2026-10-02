"""Per-agent limits from `agents.config`, with the process-wide defaults beneath."""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from labhq.scheduler import SchedulerSettings, limits_for

DEFAULTS = SchedulerSettings()


def test_concurrency_defaults_to_one() -> None:
    assert DEFAULTS.default_concurrency == 1
    assert limits_for({}, DEFAULTS).concurrency == 1


def test_agent_config_overrides_the_defaults_and_ignores_other_keys() -> None:
    limits = limits_for({"concurrency": 3, "timeout_seconds": 90, "model": "x"}, DEFAULTS)

    assert limits.concurrency == 3
    assert limits.timeout == timedelta(seconds=90)


@pytest.mark.parametrize("config", [{"concurrency": 0}, {"timeout_seconds": -1}])
def test_nonsensical_limits_are_rejected(config: dict[str, int]) -> None:
    with pytest.raises(ValidationError):
        limits_for(config, DEFAULTS)


def test_defaults_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LABHQ_SCHEDULER_DEFAULT_TIMEOUT_SECONDS", "120")
    monkeypatch.setenv("LABHQ_SCHEDULER_HEARTBEAT_LIMIT_SECONDS", "45")

    settings = SchedulerSettings()

    assert limits_for({}, settings).timeout == timedelta(seconds=120)
    assert settings.heartbeat_limit == timedelta(seconds=45)
