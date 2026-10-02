from pathlib import Path

import pytest

from labhq.settings import DATABASE_FILENAME, Settings


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("LABHQ_DATA_DIR", "LABHQ_DATABASE_URL", "LABHQ_CLI_PATH"):
        monkeypatch.delenv(name, raising=False)


def test_data_dir_defaults_to_the_platform_user_data_dir() -> None:
    assert Settings().data_dir.name == "labhq"


def test_database_url_is_derived_from_the_data_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LABHQ_DATA_DIR", str(tmp_path))
    settings = Settings()
    assert settings.data_dir == tmp_path
    assert settings.resolved_database_url == f"sqlite+aiosqlite:///{tmp_path / DATABASE_FILENAME}"


def test_database_url_can_be_overridden(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LABHQ_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    assert Settings().resolved_database_url == "sqlite+aiosqlite:///:memory:"


def test_cli_path_is_unset_by_default_and_read_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    assert Settings().cli_path is None
    monkeypatch.setenv("LABHQ_CLI_PATH", "/usr/local/bin/claude")
    assert Settings().cli_path == Path("/usr/local/bin/claude")
