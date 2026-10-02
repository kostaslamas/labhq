"""Fail when pytest collects fewer tests than the configured floor.

A suite that silently collects nothing (a bad `testpaths`, a broken conftest, a renamed
directory) would otherwise pass CI. The floor lives in `[tool.labhq.collection_floor]`.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

from tools._config import labhq_config

_SUMMARY = re.compile(r"^(\d+) tests? collected", re.MULTILINE)


def collected(root: Path, pytest_args: list[str]) -> int:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            *pytest_args,
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    match = _SUMMARY.search(result.stdout)
    if result.returncode not in (0, 5) or (match is None and result.returncode == 0):
        raise SystemExit(f"pytest collection failed:\n{result.stdout}\n{result.stderr}")
    return int(match.group(1)) if match else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--min", type=int, help="override the floor from pyproject.toml")
    parser.add_argument("pytest_args", nargs="*")
    args = parser.parse_args(argv)

    floor = args.min
    if floor is None:
        floor = int(labhq_config(args.root, "collection_floor")["min_tests"])
    if floor < 1:
        print("error: the test floor must be at least 1")
        return 1
    count = collected(args.root, args.pytest_args)
    if count < floor:
        print(f"error: pytest collected {count} tests, the floor is {floor}")
        return 1
    print(f"collection_floor: {count} tests collected, floor {floor}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
