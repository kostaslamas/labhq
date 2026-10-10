"""The two caps that close a decision room, and what the thread says when one is reached."""

from dataclasses import dataclass
from datetime import datetime

TURN_CAP_REASON = "turn_cap"
COST_CAP_REASON = "cost_cap"
# What the thread says when the room closes itself, by reason. `{spent}` and `{cap}` are USD.
CLOSING_NOTES = {
    TURN_CAP_REASON: "Turn cap reached: the room closes with its minutes.",
    COST_CAP_REASON: (
        "Cost cap reached ({spent} of {cap}): the room stops and closes with its minutes."
    ),
}


@dataclass(frozen=True)
class Spent:
    """What the room has cost so far, against the figures the owner approved it under."""

    total: int
    cap: int | None
    high: int | None
    announced_at: datetime | None
