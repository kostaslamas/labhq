"""Spoken references to a question: question 7 is "Q7".

Parsing lives with the other spoken references in `labhq.callcenter.answers.refs`.
"""

from labhq.callcenter.answers.refs import question_ref


class InvalidReferenceError(ValueError):
    pass


def format_reference(question_id: int) -> str:
    return question_ref(question_id)
