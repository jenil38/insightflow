"""
Custom exception hierarchy + global exception handlers.

Design goal: keep the JSON error shape backward compatible with the
original code (`{"detail": "..."}`, which is what the existing frontend's
axios error handling expects), while adding an `error_code` field that new
frontend code can rely on going forward.
"""

import logging
import traceback
import uuid

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("insightflow.errors")

# Starlette renamed this constant (RFC 9110 calls 422 "Unprocessable Content",
# not "Unprocessable Entity") and deprecated the old spelling, which emits a
# warning on import. Reading the new name with a fallback keeps the app quiet on
# current Starlette while still importing on the older version pinned in
# requirements.txt. The wire status code is 422 either way.
HTTP_422 = (
    getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", None)
    or status.HTTP_422_UNPROCESSABLE_ENTITY
)


class AppException(Exception):
    """Base class for all application-raised (as opposed to framework-raised) errors."""

    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "app_error"

    def __init__(
        self, detail: str, error_code: str | None = None, status_code: int | None = None
    ):
        self.detail = detail
        if error_code:
            self.error_code = error_code
        if status_code:
            self.status_code = status_code
        super().__init__(detail)


class NotFoundError(AppException):
    status_code = status.HTTP_404_NOT_FOUND
    error_code = "not_found"


class ValidationAppError(AppException):
    status_code = HTTP_422
    error_code = "validation_error"


class AuthError(AppException):
    status_code = status.HTTP_401_UNAUTHORIZED
    error_code = "auth_error"


class PermissionDeniedError(AppException):
    status_code = status.HTTP_403_FORBIDDEN
    error_code = "permission_denied"


class ConflictError(AppException):
    status_code = status.HTTP_409_CONFLICT
    error_code = "conflict"


class RateLimitedError(AppException):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    error_code = "rate_limited"


def _error_response(
    status_code: int, detail, error_code: str, request_id: str
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"detail": detail, "error_code": error_code, "request_id": request_id},
    )


def register_exception_handlers(app: FastAPI) -> None:

    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException):
        request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        logger.warning(
            "AppException: %s (%s)",
            exc.detail,
            exc.error_code,
            extra={"request_id": request_id},
        )
        return _error_response(exc.status_code, exc.detail, exc.error_code, request_id)

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        # Preserves behavior of existing `raise HTTPException(...)` calls throughout
        # the codebase - same status code and `detail` shape as before.
        request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        return _error_response(exc.status_code, exc.detail, "http_error", request_id)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ):
        request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        return _error_response(
            HTTP_422,
            exc.errors(),
            "validation_error",
            request_id,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        logger.error(
            "Unhandled exception on %s %s: %s\n%s",
            request.method,
            request.url.path,
            exc,
            traceback.format_exc(),
            extra={"request_id": request_id},
        )
        return _error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Internal server error. Our team has been notified.",
            "internal_error",
            request_id,
        )
