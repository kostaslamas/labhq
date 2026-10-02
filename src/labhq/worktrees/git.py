"""Run git as a child process and fail loudly when it fails."""

import subprocess
from collections.abc import Mapping
from pathlib import Path


class GitError(RuntimeError):
    def __init__(self, args: tuple[str, ...], returncode: int, stderr: str) -> None:
        super().__init__(f"git {' '.join(args)} exited {returncode}: {stderr.strip()}")
        self.returncode = returncode
        self.stderr = stderr


def run_git(*args: str, cwd: Path, env: Mapping[str, str] | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=None if env is None else dict(env),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise GitError(args, result.returncode, result.stderr)
    return result.stdout
