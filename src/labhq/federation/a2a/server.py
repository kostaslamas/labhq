"""The A2A request handler: an upstream's orders in, this instance's reports out.

The task store is the #188 tables. An A2A task is a `FederationInbound` (its id is the task
id) and its reports are artifacts, so a task read is a plain query and nothing here keeps
state of its own. Only the methods an upstream manager needs are served; the rest answer
with the protocol's own "unsupported" errors.
"""

from collections.abc import AsyncGenerator
from datetime import datetime

from a2a.server.context import ServerCallContext
from a2a.server.events import Event
from a2a.server.request_handlers import RequestHandler
from a2a.types import (
    AgentCard,
    Artifact,
    CancelTaskRequest,
    DeleteTaskPushNotificationConfigRequest,
    GetExtendedAgentCardRequest,
    GetTaskPushNotificationConfigRequest,
    GetTaskRequest,
    ListTaskPushNotificationConfigsRequest,
    ListTaskPushNotificationConfigsResponse,
    ListTasksRequest,
    ListTasksResponse,
    Message,
    Part,
    Role,
    SendMessageRequest,
    SubscribeToTaskRequest,
    Task,
    TaskPushNotificationConfig,
    TaskStatus,
)
from a2a.utils.errors import (
    InvalidParamsError,
    PushNotificationNotSupportedError,
    TaskNotCancelableError,
    TaskNotFoundError,
    UnsupportedOperationError,
)
from google.protobuf.json_format import MessageToDict
from google.protobuf.struct_pb2 import Struct
from google.protobuf.timestamp_pb2 import Timestamp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from labhq.cli.context import Context
from labhq.db.models import FederationInbound, FederationReport
from labhq.federation.a2a.states import (
    INITIAL_STATE,
    ORDER_ID,
    REPORT_ARTIFACT_PREFIX,
    REPORT_REF,
    REPORT_SEQ,
    REPORT_STATUS,
    SPEND_CAP,
    STATE_OF_REPORT,
)
from labhq.federation.errors import FederationError
from labhq.federation.inbound import receive_order
from labhq.federation.keys import ORDERS, REPORTS
from labhq.federation.settings import FederationSettings

# What the route's bearer check leaves in the call context for the handler.
INVITE_ID = "federation_invite_id"
SCOPES = "federation_scopes"
DEFAULT_PAGE = 50
MAX_PAGE = 100


def _struct(values: dict[str, str | int]) -> Struct:
    struct = Struct()
    struct.update(values)
    return struct


def _timestamp(moment: datetime) -> Timestamp:
    stamp = Timestamp()
    stamp.FromDatetime(moment)
    return stamp


def _text_part(text: str) -> Part:
    return Part(text=text)


def _artifact(report: FederationReport) -> Artifact:
    return Artifact(
        artifact_id=f"{REPORT_ARTIFACT_PREFIX}{report.seq}",
        name=f"{report.status} report {report.seq}",
        parts=[_text_part(report.summary)],
        metadata=_struct(
            {REPORT_SEQ: report.seq, REPORT_STATUS: report.status.value, REPORT_REF: report.ref}
        ),
    )


def task_of(inbound: FederationInbound, reports: list[FederationReport]) -> Task:
    """The A2A task an order stands for: its newest report is the status, all are artifacts."""
    latest = reports[-1] if reports else None
    status = TaskStatus(
        state=STATE_OF_REPORT[latest.status] if latest else INITIAL_STATE,
        timestamp=_timestamp(latest.created_at if latest else inbound.received_at),
    )
    if latest is not None:
        status.message.CopyFrom(
            Message(
                message_id=f"status-{inbound.id}-{latest.seq}",
                role=Role.ROLE_AGENT,
                task_id=str(inbound.id),
                context_id=str(inbound.id),
                parts=[_text_part(latest.summary)],
            )
        )
    return Task(
        id=str(inbound.id),
        context_id=str(inbound.id),
        status=status,
        artifacts=[_artifact(report) for report in reports],
    )


def order_text(message: Message) -> str:
    """The order's words, exactly as sent: text parts only, joined by a blank line."""
    if message.role != Role.ROLE_USER:
        raise InvalidParamsError(message="an order is a message from the user role")
    texts = [part.text for part in message.parts if part.WhichOneof("content") == "text"]
    if not texts or len(texts) != len(message.parts) or not "".join(texts).strip():
        raise InvalidParamsError(message="an order is one or more non-empty text parts")
    return "\n\n".join(texts)


def _metadata_int(message: Message, key: str) -> int | None:
    values = MessageToDict(message.metadata)
    value = values.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float) or value != int(value):
        raise InvalidParamsError(message=f"{key} must be a whole number")
    return int(value)


class FederationRequestHandler(RequestHandler):
    def __init__(self, context: Context, settings: FederationSettings) -> None:
        self._context = context
        self._settings = settings

    @staticmethod
    def _invite(call: ServerCallContext, scope: str) -> int:
        invite_id = call.state.get(INVITE_ID)
        if not isinstance(invite_id, int) or scope not in call.state.get(SCOPES, ()):
            # The route authenticated the key; this key may not do this call.
            raise UnsupportedOperationError(message="this key may not make that call")
        return invite_id

    async def on_message_send(
        self, params: SendMessageRequest, context: ServerCallContext
    ) -> Task | Message:
        invite_id = self._invite(context, ORDERS)
        message = params.message
        if message.task_id:
            raise InvalidParamsError(message="an order is a new task; send one message per order")
        text = order_text(message)
        order_id = _metadata_int(message, ORDER_ID)
        if order_id is None:
            raise InvalidParamsError(message=f"the message needs {ORDER_ID} in its metadata")
        cap = _metadata_int(message, SPEND_CAP)
        if cap is not None and cap <= 0:
            raise InvalidParamsError(message=f"{SPEND_CAP} must be positive")
        async with self._context.sessions() as db:
            try:
                received = await receive_order(
                    db,
                    self._context.clock,
                    upstream_name=self._settings.upstream_name,
                    upstream_order_id=order_id,
                    text=text,
                    spend_cap_micros=cap,
                )
            except FederationError as error:
                raise InvalidParamsError(message=str(error)) from None
            inbound = received.inbound
            if received.new:
                inbound.invite_id = invite_id
            elif inbound.invite_id != invite_id:
                # Another upstream's order has this number; it is not this caller's to resend.
                raise InvalidParamsError(message=f"order {order_id} is not yours")
            await db.commit()
            return task_of(inbound, await _reports(db, inbound))

    async def on_get_task(self, params: GetTaskRequest, context: ServerCallContext) -> Task | None:
        invite_id = self._invite(context, REPORTS)
        async with self._context.sessions() as db:
            inbound = await _own_inbound(db, invite_id, params.id)
            return task_of(inbound, await _reports(db, inbound))

    async def on_list_tasks(
        self, params: ListTasksRequest, context: ServerCallContext
    ) -> ListTasksResponse:
        invite_id = self._invite(context, REPORTS)
        size = min(params.page_size or DEFAULT_PAGE, MAX_PAGE)
        after = int(params.page_token) if params.page_token.isdigit() else 0
        async with self._context.sessions() as db:
            rows = list(
                await db.scalars(
                    select(FederationInbound)
                    .where(FederationInbound.invite_id == invite_id, FederationInbound.id > after)
                    .order_by(FederationInbound.id)
                    .limit(size + 1)
                )
            )
            page = rows[:size]
            tasks = [task_of(row, await _reports(db, row)) for row in page]
        more = len(rows) > size
        return ListTasksResponse(
            tasks=tasks,
            next_page_token=str(page[-1].id) if more else "",
            page_size=size,
        )

    async def on_cancel_task(
        self, params: CancelTaskRequest, context: ServerCallContext
    ) -> Task | None:
        invite_id = self._invite(context, ORDERS)
        async with self._context.sessions() as db:
            await _own_inbound(db, invite_id, params.id)
        # Work already handed to the CEO's team is not recalled by an upstream.
        raise TaskNotCancelableError(message="an order cannot be cancelled once taken")

    async def on_message_send_stream(
        self, params: SendMessageRequest, context: ServerCallContext
    ) -> AsyncGenerator[Event]:
        raise UnsupportedOperationError(message="streaming is not offered; read the task")
        yield

    async def on_subscribe_to_task(
        self, params: SubscribeToTaskRequest, context: ServerCallContext
    ) -> AsyncGenerator[Event]:
        raise UnsupportedOperationError(message="streaming is not offered; read the task")
        yield

    async def on_create_task_push_notification_config(
        self, params: TaskPushNotificationConfig, context: ServerCallContext
    ) -> TaskPushNotificationConfig:
        raise PushNotificationNotSupportedError

    async def on_get_task_push_notification_config(
        self, params: GetTaskPushNotificationConfigRequest, context: ServerCallContext
    ) -> TaskPushNotificationConfig:
        raise PushNotificationNotSupportedError

    async def on_list_task_push_notification_configs(
        self, params: ListTaskPushNotificationConfigsRequest, context: ServerCallContext
    ) -> ListTaskPushNotificationConfigsResponse:
        raise PushNotificationNotSupportedError

    async def on_delete_task_push_notification_config(
        self, params: DeleteTaskPushNotificationConfigRequest, context: ServerCallContext
    ) -> None:
        raise PushNotificationNotSupportedError

    async def on_get_extended_agent_card(
        self, params: GetExtendedAgentCardRequest, context: ServerCallContext
    ) -> AgentCard:
        raise UnsupportedOperationError(message="there is no extended card")


async def _own_inbound(db: AsyncSession, invite_id: int, task_id: str) -> FederationInbound:
    # Another key's task is "not found" to this one, not "forbidden".
    inbound = await db.get(FederationInbound, int(task_id)) if task_id.isdigit() else None
    if inbound is None or inbound.invite_id != invite_id:
        raise TaskNotFoundError
    return inbound


async def _reports(db: AsyncSession, inbound: FederationInbound) -> list[FederationReport]:
    return list(
        await db.scalars(
            select(FederationReport)
            .where(FederationReport.inbound_id == inbound.id)
            .order_by(FederationReport.seq)
        )
    )
