"""Print the API's OpenAPI schema deterministically: `python -m labhq.api.openapi`.

Sorted keys and no timestamps, so the TypeScript client generated from it changes only when
the API does.
"""

import json
import sys
from typing import Any

from labhq.api.app import create_app


def schema() -> dict[str, Any]:
    return create_app().openapi()


def render() -> str:
    return json.dumps(schema(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> None:
    sys.stdout.write(render())


if __name__ == "__main__":
    main()
