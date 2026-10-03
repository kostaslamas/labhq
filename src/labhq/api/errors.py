"""One error envelope for every API failure: `{"error": {"code": ..., "message": ...}}`.

Routes raise `ApiError` (or FastAPI's `HTTPException`); unknown routes, wrong methods, request
validation and unhandled exceptions are mapped here, so no response leaves in another shape.
"""

import logging
from collections.abc import Mapping
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)

VALIDATION_CODE = "validation_error"
INTERNAL_CODE = "internal_error"
INTERNAL_MESSAGE = "Something went wrong on the server."


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorEnvelope(BaseModel):
    error: ErrorBody


class ApiError(StarletteHTTPException):
    """An error with a machine code chosen by the route, for example `approval_not_found`."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(status_code, message, dict(headers) if headers else None)
        self.code = code


def status_code_name(status_code: int) -> str:
    """`404` -> `not_found`: the default code when a route gives none."""
    try:
        return HTTPStatus(status_code).phrase.lower().replace(" ", "_").replace("-", "_")
    except ValueError:
        return "error"


def envelope(
    status_code: int, code: str, message: str, headers: Mapping[str, str] | None = None
) -> JSONResponse:
    body = ErrorEnvelope(error=ErrorBody(code=code, message=message))
    return JSONResponse(body.model_dump(), status_code=status_code, headers=headers)


async def _http_error(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, StarletteHTTPException)
    code = getattr(error, "code", None) or status_code_name(error.status_code)
    message = (
        error.detail if isinstance(error.detail, str) else HTTPStatus(error.status_code).phrase
    )
    return envelope(error.status_code, code, message, error.headers)


async def _validation_error(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, RequestValidationError)
    problems = [
        f"{'.'.join(str(part) for part in problem.get('loc', ()))}: {problem.get('msg', '')}"
        for problem in error.errors()
    ]
    return envelope(422, VALIDATION_CODE, "; ".join(problems) or "The request is not valid.")


async def _unhandled_error(request: Request, error: Exception) -> JSONResponse:
    # The traceback stays in the log; the caller learns only that it failed.
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return envelope(500, INTERNAL_CODE, INTERNAL_MESSAGE)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(Exception, _unhandled_error)


# Declared on every operation so the generated client knows the error shape.
ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    "default": {"model": ErrorEnvelope, "description": "Error"},
}
