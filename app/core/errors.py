"""Application error types and the exception handlers that render the error envelope.

Every error the API emits has the shape:

    {"error": {"code": "SOME_CODE", "message": "...", "details": {...}}}
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("app.error")


class AppError(Exception):
    """Base class for expected, client-facing errors."""

    status_code: int = 400
    code: str = "BAD_REQUEST"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


class BadRequestError(AppError):
    status_code = 400
    code = "BAD_REQUEST"


class UnauthorizedError(AppError):
    status_code = 401
    code = "UNAUTHORIZED"


class ForbiddenError(AppError):
    status_code = 403
    code = "FORBIDDEN"


class NotFoundError(AppError):
    status_code = 404
    code = "NOT_FOUND"


class ConflictError(AppError):
    status_code = 409
    code = "CONFLICT"


def _envelope(code: str, message: str, details: dict[str, Any] | None = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Map FastAPI/pydantic validation errors into the same envelope.
        return JSONResponse(
            status_code=422,
            content=_envelope(
                "VALIDATION_ERROR",
                "Request validation failed.",
                {"errors": _jsonable(exc.errors())},
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _STATUS_CODE_NAMES.get(exc.status_code, "HTTP_ERROR")
        message = exc.detail if isinstance(exc.detail, str) else "HTTP error."
        return JSONResponse(
            status_code=exc.status_code, content=_envelope(code, message)
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content=_envelope("INTERNAL_ERROR", "An internal error occurred."),
        )


_STATUS_CODE_NAMES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
}


def _jsonable(errors: Any) -> Any:
    """pydantic v2 error dicts can carry non-serializable ctx values; coerce to str."""
    import json

    try:
        json.dumps(errors)
        return errors
    except (TypeError, ValueError):
        return json.loads(json.dumps(errors, default=str))
