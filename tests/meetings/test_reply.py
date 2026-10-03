"""Parsing the facilitator's minutes."""

import pytest

from labhq.meetings import InvalidMinutesError, parse_minutes


def test_a_fenced_reply_parses() -> None:
    reply = '```json\n{"decisions": ["Go"], "action_items": [{"title": "Do", "assignee": 3}]}\n```'

    minutes = parse_minutes(reply, {3})

    assert minutes.decisions == ["Go"]
    assert [(i.title, i.assignee, i.decision) for i in minutes.action_items] == [("Do", 3, None)]


@pytest.mark.parametrize(
    ("reply", "reason"),
    [
        (None, "empty"),
        ("no json here", "no JSON object"),
        ('{"decisions": ["Go"], "extra": 1}', "extra"),
        ('{"decisions": [" "]}', "empty"),
        (
            '{"decisions": [], "action_items": [{"title": "Do", "assignee": 3, "decision": 1}]}',
            "names no decision",
        ),
        ('{"action_items": [{"title": "Do", "assignee": 4}]}', "not a participant"),
    ],
)
def test_invalid_replies_are_refused(reply: str | None, reason: str) -> None:
    with pytest.raises(InvalidMinutesError, match=reason):
        parse_minutes(reply, {3})
