"""Owner messages retain their exact text when queued for the CEO."""

from labhq.ceochat import ConversationTurn, message_prompt, message_reason


def test_owner_message_prompt_excludes_the_stored_history() -> None:
    from datetime import UTC, datetime

    earlier = [
        ConversationTurn(1, "Earlier question", "Earlier answer", "answered", datetime.now(UTC))
    ]
    message = "Which sessions do we have?"

    assert message_prompt(message_reason(message, earlier)) == message
