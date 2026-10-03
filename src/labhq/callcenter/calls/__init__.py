"""Calls: `ask_ceo` stores the owner's words and returns a ticket; a Call Center agent per
call answers them, and `get_reply` redeems the ticket (ADR 0004)."""

from labhq.callcenter.calls.agent import ROLE, call_center_agent
from labhq.callcenter.calls.bounds import (
    BoundError,
    Interrupter,
    NoInterrupter,
    deliver_request,
    interrupt_request,
)
from labhq.callcenter.calls.service import CallCenter, Reply, Ticket, TicketState
from labhq.callcenter.calls.spoken import to_speech
from labhq.callcenter.calls.tickets import current_call, record_request
from labhq.callcenter.calls.tools import CallTools

__all__ = [
    "ROLE",
    "BoundError",
    "CallCenter",
    "CallTools",
    "Interrupter",
    "NoInterrupter",
    "Reply",
    "Ticket",
    "TicketState",
    "call_center_agent",
    "current_call",
    "deliver_request",
    "interrupt_request",
    "record_request",
    "to_speech",
]
