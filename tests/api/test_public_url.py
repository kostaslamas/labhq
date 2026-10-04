from collections.abc import Iterator

import pytest

from labhq.api.public_url import announce_exposure, approval_link, current_public_url


@pytest.fixture(autouse=True)
def no_exposure(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("LABHQ_PUBLIC_URL", raising=False)
    announce_exposure(None)
    yield
    announce_exposure(None)


def test_no_url_is_known_by_default() -> None:
    assert current_public_url() is None
    assert approval_link(3) is None


def test_the_configured_url_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LABHQ_PUBLIC_URL", "https://labhq.example.test/")
    assert approval_link(3) == "https://labhq.example.test/approve/3"


def test_a_running_exposure_is_used_without_a_trailing_slash() -> None:
    announce_exposure("https://abc.tunnel.test/")
    assert approval_link(5) == "https://abc.tunnel.test/approve/5"


def test_the_configured_url_wins_over_the_exposure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LABHQ_PUBLIC_URL", "https://labhq.example.test")
    announce_exposure("https://abc.tunnel.test")
    assert current_public_url() == "https://labhq.example.test"


def test_closing_the_exposure_forgets_it() -> None:
    announce_exposure("https://abc.tunnel.test")
    announce_exposure(None)
    assert current_public_url() is None
