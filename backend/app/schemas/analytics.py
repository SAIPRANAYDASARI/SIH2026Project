"""Request/response contracts for feedback and the officer analytics
dashboard (Step 11)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class FeedbackRequest(BaseModel):
    rating: int = Field(ge=-1, le=1)
    comment: str | None = Field(default=None, max_length=1000)


class IntentCount(BaseModel):
    intent: str
    count: int


class AnalyticsSummary(BaseModel):
    total_conversations: int
    total_assistant_messages: int
    intent_distribution: list[IntentCount]
    guardrail_violation_count: int
    forced_refusal_count: int
    forced_refusal_rate: float
    average_latency_ms: float | None
    feedback_thumbs_up: int
    feedback_thumbs_down: int
    feedback_response_rate: float
