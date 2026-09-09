"""RFC 7807 problem-detail exception handling.

Every error this API returns — validation failures, HTTP exceptions, and
uncaught exceptions in non-production environments — is normalized into a
`ProblemDetail` body via these handlers, registered once in `app.main`.
Route handlers should raise `AppError` (or a subclass) rather than building
error responses themselves.
"""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger
from app.schemas.common import ProblemDetail

logger = get_logger(__name__)

PROBLEM_CONTENT_TYPE = "application/problem+json"


class AppError(Exception):
    """Base class for application errors that map cleanly to a problem detail."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    title: str = "Application error"
    type_suffix: str = "application-error"

    def __init__(self, detail: str, *, instance: str | None = None) -> None:
        self.detail = detail
        self.instance = instance
        super().__init__(detail)


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    title = "Resource not found"
    type_suffix = "not-found"


class RateLimitedError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    title = "Rate limit exceeded"
    type_suffix = "rate-limited"


def _problem_response(
    status_code: int, title: str, detail: str, type_suffix: str, instance: str
) -> JSONResponse:
    body = ProblemDetail(
        type=f"https://manak-sahayak.dev/errors/{type_suffix}",
        title=title,
        status=status_code,
        detail=detail,
        instance=instance,
    )
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(),
        media_type=PROBLEM_CONTENT_TYPE,
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return _problem_response(
            exc.status_code, exc.title, exc.detail, exc.type_suffix, str(request.url.path)
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _problem_response(
            exc.status_code, "HTTP error", str(exc.detail), "http-error", str(request.url.path)
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _problem_response(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Validation failed",
            str(exc.errors()),
            "validation-error",
            str(request.url.path),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception", path=str(request.url.path))
        return _problem_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Internal server error",
            "An unexpected error occurred. This has been logged.",
            "internal-error",
            str(request.url.path),
        )
