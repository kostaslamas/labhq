"""Read `[tool.labhq.*]` sections from a project's pyproject.toml."""

import tomllib
from pathlib import Path
from typing import Any


def labhq_config(root: Path, section: str) -> dict[str, Any]:
    with (root / "pyproject.toml").open("rb") as handle:
        data = tomllib.load(handle)
    try:
        config: dict[str, Any] = data["tool"]["labhq"][section]
    except KeyError as error:
        raise SystemExit(f"pyproject.toml has no [tool.labhq.{section}] section") from error
    return config
