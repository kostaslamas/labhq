"""Prompts for a meeting turn and for the minutes.

A turn carries the agenda, the transcript so far and the terse agent style: what one agent
says in a round is read by every agent after it (plan §7.1).
"""

from collections.abc import Sequence
from dataclasses import dataclass

from labhq.economy import default_registry as style_registry
from labhq.meetings.kinds import MeetingKind
from labhq.meetings.transcript import Line

# Meeting rounds are agent-to-agent text, so they take the terse agent style (plan §7.1).
MEETING_STYLE = style_registry().get("agent").instruction
MINUTES_SHAPE = (
    'Reply with one JSON object and nothing else: {"decisions": ["..."], "action_items": '
    '[{"title": "...", "assignee": <agent id>, "decision": <1-based decision number or '
    "null>}]}. Assign each action item to one participant by id."
)


@dataclass(frozen=True)
class Seat:
    """A participant as prompts name it."""

    agent_id: int
    name: str
    role: str


def turn_prompt(
    *,
    kind: MeetingKind,
    project: str,
    agenda: str,
    seat: Seat,
    round_number: int,
    transcript: Sequence[Line],
) -> str:
    return "\n\n".join(
        (
            f"You are {seat.name} ({seat.role}) in a {kind.key} meeting of project {project}.",
            f"Agenda:\n{agenda}",
            _transcript(transcript),
            f"Round {round_number} of {kind.rounds}. Take your turn: one short contribution.",
            MEETING_STYLE,
        )
    )


def minutes_prompt(
    *,
    kind: MeetingKind,
    project: str,
    agenda: str,
    seats: Sequence[Seat],
    transcript: Sequence[Line],
    previous_error: str | None = None,
) -> str:
    roster = "\n".join(f"- id {seat.agent_id}: {seat.name} ({seat.role})" for seat in seats)
    parts = [
        f"You facilitated a {kind.key} meeting of project {project}. Write its minutes.",
        f"Agenda:\n{agenda}",
        f"Participants:\n{roster}",
        _transcript(transcript),
        kind.minutes_instruction,
        MINUTES_SHAPE,
    ]
    if previous_error is not None:
        parts.append(f"Your previous reply was not valid minutes: {previous_error}")
    return "\n\n".join(parts)


def _transcript(transcript: Sequence[Line]) -> str:
    if not transcript:
        return "Transcript so far: (empty)"
    body = "\n".join(f"[{line.speaker}] {line.text}" for line in transcript)
    return f"Transcript so far:\n{body}"


def room_turn_prompt(
    *,
    project: str,
    seat: Seat,
    others: Sequence[Seat],
    proposal: str | None,
    transcript: Sequence[Line],
) -> str:
    """One turn in a live decision room: the pinned proposal, the thread so far, the rules."""
    present = ", ".join(f"{other.name} ({other.role})" for other in others)
    parts = [
        f"You are {seat.name} ({seat.role}) in a live decision room of project {project}, "
        f"with the owner and {present}.",
        f"Proposal under discussion:\n{proposal}" if proposal else "No proposal is pinned.",
        _transcript(transcript),
        "Add one short contribution that answers the owner and the others. The owner decides: "
        "suggest, never announce a decision for them. Nothing said here is done until the owner "
        "confirms it afterwards. Relay only what was agreed in this thread, in the same words.",
        MEETING_STYLE,
    ]
    return "\n\n".join(parts)
