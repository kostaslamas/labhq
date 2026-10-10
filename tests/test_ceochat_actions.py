"""Action markers at the end of a CEO reply become buttons and leave the text."""

from labhq.ceochat_actions import ReplyAction, split_actions


def test_trailing_markers_become_actions_in_order() -> None:
    text, actions = split_actions(
        "I would approve it.\n\n[[approve approval:12]]\n[[show report:3]]\n"
    )

    assert text == "I would approve it."
    assert actions == [ReplyAction("approve", "approval", 12), ReplyAction("show", "report", 3)]


def test_a_marker_in_the_middle_of_the_text_stays_text() -> None:
    reply = "Use [[approve approval:1]] later.\nThen wait."

    assert split_actions(reply) == (reply, [])


def test_a_verb_cannot_name_a_kind_it_does_not_allow() -> None:
    reply = "Done.\n[[approve report:3]]"

    assert split_actions(reply) == (reply, [])


def test_an_unknown_verb_is_not_a_button() -> None:
    reply = "Done.\n[[delete project:1]]"

    assert split_actions(reply) == (reply, [])
