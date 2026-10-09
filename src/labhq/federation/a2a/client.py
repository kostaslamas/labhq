"""The upstream's A2A client for one node: send an order, read its task back.

Built on the SDK's client with streaming off: the node is read with `GetTask`, so it never
dials back and may sit behind NAT as long as it serves A2A. The key is the node's federation
key, sent as a bearer token on every call.
"""

from types import TracebackType
from typing import Self

import httpx
from a2a.client import ClientConfig, ClientFactory
from a2a.client.client import Client
from a2a.types import GetTaskRequest, Message, Part, Role, SendMessageRequest, Task
from a2a.utils.errors import A2AError
from google.protobuf.struct_pb2 import Struct

from labhq.federation.a2a.states import ORDER_ID, SPEND_CAP
from labhq.federation.errors import FederationError, UnauthorizedError

REFUSED_STATUSES = ("401", "403")


def _failure(error: Exception) -> FederationError:
    """One line an operator can act on. The key is in a header, never in the message."""
    if any(status in str(error) for status in REFUSED_STATUSES):
        return UnauthorizedError("the node refused the key: it is revoked or unknown there")
    return FederationError(f"the node did not take the A2A call: {error}")


class NodeA2aClient:
    def __init__(
        self,
        base_url: str,
        key: str,
        *,
        timeout: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._http = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {key}"}, timeout=timeout, transport=transport
        )
        self._client: Client | None = None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._client is not None:
            await self._client.close()
        await self._http.aclose()

    async def _resolved(self) -> Client:
        # The card is fetched once per client: it names the interface orders are posted to.
        if self._client is None:
            config = ClientConfig(streaming=False, httpx_client=self._http)
            try:
                self._client = await ClientFactory(config).create_from_url(self._base_url)
            except A2AError as error:
                raise _failure(error) from error
        return self._client

    async def send_order(self, order_id: int, text: str, spend_cap_micros: int | None) -> Task:
        """Send one order as one message and return the task the node opened for it."""
        metadata = Struct()
        metadata.update(
            {ORDER_ID: order_id} | ({SPEND_CAP: spend_cap_micros} if spend_cap_micros else {})
        )
        request = SendMessageRequest(
            message=Message(
                message_id=f"order-{order_id}",
                role=Role.ROLE_USER,
                parts=[Part(text=text)],
                metadata=metadata,
            )
        )
        client = await self._resolved()
        try:
            async for response in client.send_message(request):
                if response.HasField("task"):
                    return response.task
        except A2AError as error:
            raise _failure(error) from error
        raise FederationError("the node answered an order without a task")

    async def get_task(self, task_id: str) -> Task:
        client = await self._resolved()
        try:
            return await client.get_task(GetTaskRequest(id=task_id))
        except A2AError as error:
            raise _failure(error) from error
