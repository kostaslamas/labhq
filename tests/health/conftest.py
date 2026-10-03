from pathlib import Path

import pytest

from tests.health.factories import StubPsutil


@pytest.fixture
def stub_psutil(monkeypatch: pytest.MonkeyPatch) -> StubPsutil:
    stub = StubPsutil()
    stub.install(monkeypatch)
    return stub


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Tickets create the infra project's directory here, never in the developer's data."""
    path = tmp_path / "data"
    monkeypatch.setenv("LABHQ_DATA_DIR", str(path))
    return path
