"""The facilitator's minutes, as JSON validated by a Pydantic model."""

from collections.abc import Collection

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class InvalidMinutesError(ValueError):
    pass


class ActionItemReply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=300)
    # An agent id from the participant list in the prompt.
    assignee: int
    # 1-based position of the decision the item follows from, if any.
    decision: int | None = None


class MinutesReply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decisions: list[str] = Field(default_factory=list)
    action_items: list[ActionItemReply] = Field(default_factory=list)

    @model_validator(mode="after")
    def _decisions_exist(self) -> "MinutesReply":
        for item in self.action_items:
            if item.decision is not None and not 1 <= item.decision <= len(self.decisions):
                raise ValueError(f"action item {item.title!r} names no decision {item.decision}")
        if any(not text.strip() for text in self.decisions):
            raise ValueError("a decision is empty")
        return self


def parse_minutes(text: str | None, assignees: Collection[int]) -> MinutesReply:
    """Validate a reply; tolerate a code fence or prose around one JSON object."""
    if not text:
        raise InvalidMinutesError("the reply is empty")
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise InvalidMinutesError("the reply holds no JSON object")
    try:
        minutes = MinutesReply.model_validate_json(text[start : end + 1])
    except ValidationError as error:
        raise InvalidMinutesError(str(error)) from error
    for item in minutes.action_items:
        if item.assignee not in assignees:
            raise InvalidMinutesError(
                f"action item {item.title!r} is assigned to {item.assignee}, not a participant"
            )
    return minutes
