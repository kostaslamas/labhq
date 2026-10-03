"""What a gate adapter does, and the registry new gate kinds join."""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

import httpx

from labhq.approvals.gates.settings import GateSettings
from labhq.approvals.registry import Registry


class GateError(RuntimeError):
    """A gate call failed. The message never carries the token or a response body."""


class GateStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


@dataclass(frozen=True)
class GateRequest:
    command: str
    cwd: str


@dataclass(frozen=True)
class GateAnswer:
    status: GateStatus
    # What proved the answer (`passkey`, `password`, ...); None while pending.
    via: str | None = None


class GateAdapter(Protocol):
    async def send(self, request: GateRequest) -> str:
        """Hand the request to the gate and return the gate's id for it."""
        ...

    async def status(self, request_id: str) -> GateAnswer: ...


type GateFactory = Callable[[GateSettings, httpx.AsyncClient], GateAdapter]

gate_adapters = Registry[GateFactory]("gate adapter")


def build_gate(settings: GateSettings, client: httpx.AsyncClient) -> GateAdapter:
    return gate_adapters.get(settings.kind)(settings, client)
