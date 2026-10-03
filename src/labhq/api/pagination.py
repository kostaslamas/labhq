"""Keyset (cursor) pagination: opaque cursor, `limit`, `next_cursor`.

The cursor records the sort key of the last row served, not an offset, so rows inserted
between requests never shift a page: no row is served twice and none is skipped. The sort
key must be unique; end it with the primary key.
"""

import base64
import binascii
import json
from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Any

from fastapi import Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import Select, literal, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from labhq.api.errors import ApiError
from labhq.clock import ensure_utc

INVALID_CURSOR_CODE = "invalid_cursor"
_DATETIME_TAG = "dt"


class Page[T](BaseModel):
    items: list[T]
    # Absent on the last page.
    next_cursor: str | None


class PageParams(BaseModel):
    cursor: str | None
    limit: int


def _invalid_cursor() -> ApiError:
    return ApiError(400, INVALID_CURSOR_CODE, "The cursor is not valid; start from the first page.")


def _encode_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return {_DATETIME_TAG: ensure_utc(value).isoformat()}
    return value


def _decode_value(value: Any) -> Any:
    if isinstance(value, dict):
        return datetime.fromisoformat(value[_DATETIME_TAG])
    return value


def encode_cursor(key: Sequence[Any]) -> str:
    raw = json.dumps([_encode_value(value) for value in key], separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str, width: int) -> list[Any]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        values = json.loads(raw)
        if not isinstance(values, list) or len(values) != width:
            raise _invalid_cursor()
        return [_decode_value(value) for value in values]
    except (binascii.Error, UnicodeDecodeError, ValueError, KeyError, TypeError) as error:
        raise _invalid_cursor() from error


def page_params(
    request: Request,
    cursor: Annotated[str | None, Query(description="Opaque; from `next_cursor`.")] = None,
    limit: Annotated[int | None, Query(ge=1, description="Rows per page.")] = None,
) -> PageParams:
    settings = request.app.state.settings
    chosen = settings.default_page_size if limit is None else limit
    return PageParams(cursor=cursor, limit=min(chosen, settings.max_page_size))


PageParamsDep = Annotated[PageParams, Depends(page_params)]


async def paginate[R](
    session: AsyncSession,
    statement: Select[R],
    key: Sequence[InstrumentedAttribute[Any]],
    params: PageParams,
) -> tuple[list[R], str | None]:
    """One page of `statement`'s rows in ascending `key` order, and the next cursor."""
    if params.cursor is not None:
        after = decode_cursor(params.cursor, len(key))
        # Bound with each column's type, so a datetime is stored-format UTC like the column.
        bound = [literal(value, column.type) for value, column in zip(after, key, strict=True)]
        statement = statement.where(tuple_(*key) > tuple_(*bound))
    statement = statement.order_by(*key).limit(params.limit + 1)
    rows = list((await session.scalars(statement)).all())
    if len(rows) <= params.limit:
        return rows, None
    rows = rows[: params.limit]
    last = rows[-1]
    return rows, encode_cursor([getattr(last, column.key) for column in key])
