"""Shared response envelopes, incl. RFC 7807 problem-detail errors."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ProblemDetail(BaseModel):
    """RFC 7807 error body, returned by every error response in this API."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "type": "https://manak-sahayak.dev/errors/rate-limited",
                "title": "Rate limit exceeded",
                "status": 429,
                "detail": "You have exceeded 20 requests per minute.",
                "instance": "/api/v1/chat",
            }
        }
    )

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None


class HealthStatus(BaseModel):
    status: str
    database: str
    redis: str
    app_env: str
    llm_backend: str
