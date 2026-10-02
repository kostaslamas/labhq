from pathlib import Path

import pytest

from tools import collection_floor

PYPROJECT = """
[tool.labhq.collection_floor]
min_tests = {floor}

[tool.pytest.ini_options]
testpaths = ["tests"]
"""


def _project(root: Path, tests: int, floor: int = 1) -> Path:
    (root / "pyproject.toml").write_text(PYPROJECT.format(floor=floor))
    (root / "tests").mkdir()
    body = "".join(f"def test_{index}() -> None:\n    pass\n\n" for index in range(tests))
    (root / "tests" / "test_sample.py").write_text(body)
    return root


def test_zero_collected_tests_fail(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _project(tmp_path, tests=0)
    assert collection_floor.main(["--root", str(root)]) == 1
    assert "collected 0 tests" in capsys.readouterr().out


def test_fewer_tests_than_the_floor_fail(tmp_path: Path) -> None:
    root = _project(tmp_path, tests=2, floor=3)
    assert collection_floor.main(["--root", str(root)]) == 1


def test_reaching_the_floor_passes(tmp_path: Path) -> None:
    root = _project(tmp_path, tests=3, floor=3)
    assert collection_floor.main(["--root", str(root)]) == 0


def test_a_floor_below_one_is_refused(tmp_path: Path) -> None:
    root = _project(tmp_path, tests=3)
    assert collection_floor.main(["--root", str(root), "--min", "0"]) == 1


def test_a_collection_error_fails_loudly(tmp_path: Path) -> None:
    root = _project(tmp_path, tests=1)
    (root / "tests" / "test_broken.py").write_text("import does_not_exist\n")
    with pytest.raises(SystemExit, match="collection failed"):
        collection_floor.main(["--root", str(root)])
