"""TOML inline values, as Codex parses the right side of `-c key=value`."""

import json


def toml_value(value: object) -> str:
    """A TOML inline value, as Codex parses the right side of `-c key=value`."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        # A JSON string without ASCII escapes is a TOML basic string.
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        pairs = (f"{key} = {toml_value(item)}" for key, item in value.items())
        return "{" + ", ".join(pairs) + "}"
    raise TypeError(f"no TOML form for {type(value).__name__}")
