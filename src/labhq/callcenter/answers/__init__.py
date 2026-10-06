"""Answers the program gives from its own database, with no agent and no model."""

from labhq.callcenter.answers.daily import brief
from labhq.callcenter.answers.inbox import inbox
from labhq.callcenter.answers.refs import approval_ref, parse_ref, question_ref
from labhq.callcenter.answers.reports import reports
from labhq.callcenter.answers.status import health

__all__ = ["approval_ref", "brief", "health", "inbox", "parse_ref", "question_ref", "reports"]
