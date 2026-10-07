"""The federation endpoint's request and response bodies, shared by server and client."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from labhq.db.enums import UpstreamStatus

API_PATH = "/api/federation"
ORDERS_PATH = f"{API_PATH}/orders"
REPORTS_PATH = f"{API_PATH}/reports"


def ack_path(order_id: int) -> str:
    return f"{ORDERS_PATH}/{order_id}/ack"


class WireOrder(BaseModel):
    id: int
    text: str
    spend_cap_micros: int | None
    created_at: datetime


class OrdersBody(BaseModel):
    orders: list[WireOrder]


class ReportBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: int
    # Per-order, rising: the upstream applies a sequence number once.
    seq: int = Field(ge=1)
    status: UpstreamStatus
    summary: str = Field(min_length=1, max_length=500)
    ref: str = Field(default="", max_length=100)


class Accepted(BaseModel):
    # False when the upstream had already applied this report.
    applied: bool = True
