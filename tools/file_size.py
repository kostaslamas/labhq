"""File size guard (CONTRIBUTING.md §2): warn past the soft limit, fail past the hard one.

Limits, roots and dated exemptions live in `[tool.labhq.file_size]` in pyproject.toml.
"""

import argparse
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from tools._config import labhq_config


@dataclass(frozen=True)
class Exemption:
    path: str
    date: date
    reason: str


@dataclass(frozen=True)
class Report:
    warnings: list[str]
    failures: list[str]
    checked: int

    @property
    def ok(self) -> bool:
        return not self.failures


def _parse_exemptions(raw: list[dict[str, object]]) -> dict[str, Exemption]:
    exemptions: dict[str, Exemption] = {}
    for entry in raw:
        path, when, reason = entry.get("path"), entry.get("date"), entry.get("reason")
        if not isinstance(path, str) or not isinstance(reason, str) or not reason.strip():
            raise SystemExit(f"file_size exemption needs a path and a reason: {entry}")
        if not isinstance(when, date):
            raise SystemExit(f"file_size exemption needs a date (YYYY-MM-DD): {entry}")
        exemptions[path] = Exemption(path, when, reason)
    return exemptions


def count_lines(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def check(root: Path) -> Report:
    config = labhq_config(root, "file_size")
    soft, hard = int(config["soft_limit"]), int(config["hard_limit"])
    suffixes = set(config["suffixes"])
    exemptions = _parse_exemptions(config.get("exemptions", []))

    files = sorted(
        path
        for name in config["roots"]
        if (root / name).is_dir()
        for path in (root / name).rglob("*")
        if path.is_file() and path.suffix in suffixes
    )
    if not files:
        # A guard that checked nothing must not pass (CONTRIBUTING.md §6).
        return Report([], [f"no files matched roots {config['roots']}"], 0)

    warnings: list[str] = []
    failures: list[str] = []
    for path in files:
        relative = path.relative_to(root).as_posix()
        lines = count_lines(path)
        exemption = exemptions.pop(relative, None)
        if lines > hard and exemption is None:
            failures.append(f"{relative}: {lines} lines, hard limit {hard}")
        elif lines > soft:
            note = f" (exempt since {exemption.date}: {exemption.reason})" if exemption else ""
            warnings.append(f"{relative}: {lines} lines, soft limit {soft}{note}")
    warnings.extend(f"{path}: exemption for a file that no longer exists" for path in exemptions)
    return Report(warnings, failures, len(files))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)

    report = check(args.root)
    for line in report.warnings:
        print(f"warning: {line}")
    for line in report.failures:
        print(f"error: {line}")
    print(f"file_size: {report.checked} files checked, {len(report.failures)} over the limit")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
