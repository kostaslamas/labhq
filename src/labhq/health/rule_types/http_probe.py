"""`http`: a port accepts connections, or a URL answers with the expected status in time.

An active probe, not a sample: it runs when the rule is evaluated. The probe is a module
attribute read at call time, so tests replace it and never touch the network.
"""

import asyncio
import logging
from typing import Protocol, Self

import httpx
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from labhq.db.models import Host
from labhq.health.rules import Evaluation, RuleContext, registry

logger = logging.getLogger(__name__)

LOOPBACK = "127.0.0.1"


class HttpParams(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    url: HttpUrl | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    # Where the port is probed; default: the host's address, or loopback for the local host.
    address: str | None = Field(default=None, min_length=1)
    expected_status: int = Field(default=200, ge=100, le=599)
    timeout_seconds: float = Field(default=5.0, gt=0, le=60)

    @model_validator(mode="after")
    def _one_target(self) -> Self:
        if (self.url is None) == (self.port is None):
            raise ValueError("give exactly one of url and port")
        return self


class Probe(Protocol):
    async def connects(self, address: str, port: int, timeout: float) -> bool: ...

    async def status(self, url: str, timeout: float) -> int | None: ...


class NetworkProbe:
    async def connects(self, address: str, port: int, timeout: float) -> bool:
        try:
            _, writer = await asyncio.wait_for(asyncio.open_connection(address, port), timeout)
        except (OSError, TimeoutError):
            return False
        writer.close()
        await writer.wait_closed()
        return True

    async def status(self, url: str, timeout: float) -> int | None:
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                return (await client.get(url)).status_code
        except httpx.HTTPError:
            return None


probe: Probe = NetworkProbe()


def _address(params: HttpParams, host: Host) -> str | None:
    if params.address is not None:
        return params.address
    if host.address is not None:
        return host.address
    return LOOPBACK if host.is_local else None


async def _check_port(params: HttpParams, port: int, host: Host) -> Evaluation:
    address = _address(params, host)
    if address is None:
        logger.warning("http rule: host %s has no address to probe", host.name)
        return Evaluation(violated=False)
    if await probe.connects(address, port, params.timeout_seconds):
        return Evaluation(violated=False)
    target = f"{address}:{port}"
    return Evaluation(violated=True, details={"target": target, "observed": "refused or timeout"})


async def _check_url(params: HttpParams, url: str) -> Evaluation:
    status = await probe.status(url, params.timeout_seconds)
    if status == params.expected_status:
        return Evaluation(violated=False)
    return Evaluation(
        violated=True,
        details={"target": url, "expected_status": params.expected_status, "observed": status},
    )


@registry.register("http", HttpParams)
async def evaluate_http(context: RuleContext) -> Evaluation:
    params = HttpParams.model_validate(context.rule.params)
    if params.port is not None:
        return await _check_port(params, params.port, context.host)
    return await _check_url(params, str(params.url))
