"""The generic HTTP gate: POST a request, GET its status, both with a token header."""

from typing import Any

import httpx

from labhq.approvals.gates.base import (
    GateAnswer,
    GateError,
    GateRequest,
    GateStatus,
    gate_adapters,
)
from labhq.approvals.gates.settings import GateSettings


class HttpGate:
    def __init__(self, settings: GateSettings, client: httpx.AsyncClient) -> None:
        if not settings.configured or settings.token is None or settings.base_url is None:
            raise GateError("no gate is configured; set LABHQ_GATE_BASE_URL and LABHQ_GATE_TOKEN")
        self._base = settings.base_url.rstrip("/")
        self._request_path = settings.request_path
        self._status_path = settings.status_path
        self._headers = {settings.token_header: settings.token.get_secret_value()}
        self._client = client

    async def send(self, request: GateRequest) -> str:
        body = {"command": request.command, "cwd": request.cwd}
        data = await self._call("POST", self._base + self._request_path, json=body)
        request_id = data.get("id")
        if request_id is None or request_id == "":
            raise GateError("the gate answered without a request id")
        return str(request_id)

    async def status(self, request_id: str) -> GateAnswer:
        url = self._base + self._status_path.format(id=request_id)
        data = await self._call("GET", url)
        try:
            status = GateStatus(str(data.get("status")).lower())
        except ValueError:
            raise GateError("the gate answered with an unknown status") from None
        via = data.get("via")
        return GateAnswer(status, str(via).lower() if via else None)

    async def _call(self, method: str, url: str, **options: Any) -> dict[str, Any]:
        try:
            response = await self._client.request(method, url, headers=self._headers, **options)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as error:
            # Only the status code: neither request headers nor the body belong in an error.
            raise GateError(f"the gate answered HTTP {error.response.status_code}") from None
        except (httpx.HTTPError, ValueError) as error:
            raise GateError(f"the gate call failed ({type(error).__name__})") from None
        if not isinstance(data, dict):
            raise GateError("the gate answered with something other than a JSON object")
        return data


gate_adapters.register("http", HttpGate)
