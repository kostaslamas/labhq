import pytest

from labhq.callcenter.settings import CallCenterSettings, get_callcenter_settings


def test_defaults() -> None:
    settings = CallCenterSettings()
    assert (settings.call_window_seconds, settings.ticket_expiry_seconds) == (300, 3600)


def test_environment_overrides_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LABHQ_CALLCENTER_CALL_WINDOW_SECONDS", "60")
    monkeypatch.setenv("LABHQ_CALLCENTER_TICKET_EXPIRY_SECONDS", "120")
    settings = CallCenterSettings()
    assert (settings.call_window_seconds, settings.ticket_expiry_seconds) == (60, 120)


def test_getter_is_cached() -> None:
    assert get_callcenter_settings() is get_callcenter_settings()
