from pathlib import Path

import pytest

from tools import file_size

PYPROJECT = """
[tool.labhq.file_size]
roots = ["src", "tests", "tools"]
suffixes = [".py"]
soft_limit = 400
hard_limit = 600
exemptions = [{exemptions}]
"""


def _project(root: Path, files: dict[str, int], exemptions: str = "") -> Path:
    (root / "pyproject.toml").write_text(PYPROJECT.format(exemptions=exemptions))
    for relative, lines in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x = 1\n" * lines)
    return root


def test_a_601_line_file_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _project(tmp_path, {"src/big.py": 601, "src/ok.py": 10})
    assert file_size.main(["--root", str(root)]) == 1
    assert "src/big.py: 601 lines, hard limit 600" in capsys.readouterr().out


def test_a_401_line_file_warns_and_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _project(tmp_path, {"tests/long_test.py": 401})
    assert file_size.main(["--root", str(root)]) == 0
    assert "warning: tests/long_test.py: 401 lines, soft limit 400" in capsys.readouterr().out


def test_files_at_the_limits_pass_quietly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _project(tmp_path, {"tools/a.py": 400})
    assert file_size.main(["--root", str(root)]) == 0
    assert "warning" not in capsys.readouterr().out


def test_a_dated_exemption_lets_a_long_file_pass(tmp_path: Path) -> None:
    exemption = '{ path = "src/big.py", date = 2026-10-02, reason = "split in #99" }'
    root = _project(tmp_path, {"src/big.py": 700}, exemption)
    report = file_size.check(root)
    assert report.ok
    assert "exempt since 2026-10-02: split in #99" in report.warnings[0]


def test_an_exemption_without_a_date_is_a_configuration_error(tmp_path: Path) -> None:
    root = _project(tmp_path, {"src/big.py": 700}, '{ path = "src/big.py", reason = "later" }')
    with pytest.raises(SystemExit, match="needs a date"):
        file_size.check(root)


def test_an_exemption_without_a_reason_is_a_configuration_error(tmp_path: Path) -> None:
    root = _project(tmp_path, {"src/big.py": 700}, '{ path = "src/big.py", date = 2026-10-02 }')
    with pytest.raises(SystemExit, match="needs a path and a reason"):
        file_size.check(root)


def test_files_outside_the_roots_are_ignored(tmp_path: Path) -> None:
    root = _project(tmp_path, {"migrations/versions/0001.py": 900, "src/ok.py": 1})
    assert file_size.check(root).ok


def test_checking_nothing_fails(tmp_path: Path) -> None:
    root = _project(tmp_path, {})
    assert not file_size.check(root).ok


def test_the_repository_passes() -> None:
    assert file_size.check(Path(__file__).resolve().parents[2]).ok
