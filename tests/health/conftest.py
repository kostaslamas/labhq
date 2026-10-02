import pytest

from tests.health.factories import StubPsutil


@pytest.fixture
def stub_psutil(monkeypatch: pytest.MonkeyPatch) -> StubPsutil:
    stub = StubPsutil()
    stub.install(monkeypatch)
    return stub
