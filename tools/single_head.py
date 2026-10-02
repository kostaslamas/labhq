"""Fail unless the Alembic history has exactly one head.

Two parallel branches that each add a migration merge cleanly in git but leave two heads;
`alembic upgrade head` then refuses to run. Catch it in CI instead.
"""

import argparse
import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def heads(script_location: Path) -> list[str]:
    config = Config()
    config.set_main_option("script_location", str(script_location))
    return list(ScriptDirectory.from_config(config).get_heads())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--migrations", type=Path, default=Path("migrations"))
    args = parser.parse_args(argv)

    found = heads(args.migrations)
    if len(found) == 1:
        print(f"single_head: one Alembic head ({found[0]})")
        return 0
    print(
        f"error: expected exactly one Alembic head, found {len(found)}: {', '.join(found)}. "
        "Rebase onto main and re-parent your migration."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
