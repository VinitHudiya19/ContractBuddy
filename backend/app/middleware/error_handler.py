"""
Global exception handlers → one uniform JSON error envelope:

    {"error": {"code": "...", "message": "...", "request_id": "..."}}

`AppError`s map to their declared code/status. FastAPI request-validation errors
become a 422 with field details. Anything unhandled becomes a safe 500 (no
internals leaked) but is logged with a full stack trace and the request_id.
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import AppError
from app.core.logging import get_logger, request_id_ctx

logger = get_logger(__name__)


def _envelope(code: str, message: str, request_id: str | None, details=None) -> dict:
    error: dict = {"code": code, "message": message, "request_id": request_id}
    if details is not None:
        error["details"] = details
    return {"error": error}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        rid = request_id_ctx.get()
        if exc.status_code >= 500:
            logger.error("app error", extra={"code": exc.code}, exc_info=exc)
        else:
            logger.info("handled error", extra={"code": exc.code, "error_message": exc.message})
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(exc.code, exc.message, rid),
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        rid = request_id_ctx.get()
        details = [
            {"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]}
            for e in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=_envelope("VALIDATION_ERROR", "Request validation failed.", rid, details),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        rid = request_id_ctx.get()
        code = {401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(
            exc.status_code, "HTTP_ERROR"
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(code, str(exc.detail), rid),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        rid = request_id_ctx.get()
        logger.error("unhandled exception", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content=_envelope("INTERNAL_ERROR", "An unexpected error occurred.", rid),
        )
