"""Aggregation queries for the officer analytics dashboard (Step 11).

`retrieval_debug` and `citations` are opaque JSONB columns (see
`app.models.conversation.Message`), and this dataset is small enough for a
hackathon-scale deployment that we fetch assistant messages and aggregate
in Python rather than writing JSON-operator SQL that would differ between
SQLite (tests) and Postgres (production) — see docs/DECISIONS.md, Step 11,
for why this trade-off was made and what a production version would do
differently (a materialized `message_stats` table refreshed by a Celery
task, so this stays O(1) instead of O(messages) as the table grows).
"""

from __future__ import annotations

from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation, Message, MessageRole
from app.schemas.analytics import AnalyticsSummary, IntentCount


async def compute_summary(session: AsyncSession) -> AnalyticsSummary:
    total_conversations = (
        await session.execute(select(func.count()).select_from(Conversation))
    ).scalar_one()

    assistant_stmt = select(Message).where(Message.role == MessageRole.ASSISTANT)
    assistant_messages = list((await session.execute(assistant_stmt)).scalars())

    total_assistant_messages = len(assistant_messages)
    intent_counter: Counter[str] = Counter()
    guardrail_violation_count = 0
    forced_refusal_count = 0
    latencies: list[int] = []
    thumbs_up = 0
    thumbs_down = 0
    rated = 0

    for message in assistant_messages:
        if message.intent:
            intent_counter[message.intent] += 1
        debug = message.retrieval_debug or {}
        violations = debug.get("guardrail_violations") or []
        if violations:
            guardrail_violation_count += 1
        if debug.get("forced_refusal"):
            forced_refusal_count += 1
        if message.latency_ms is not None:
            latencies.append(message.latency_ms)
        if message.feedback_rating is not None and message.feedback_rating != 0:
            rated += 1
            if message.feedback_rating > 0:
                thumbs_up += 1
            else:
                thumbs_down += 1

    return AnalyticsSummary(
        total_conversations=total_conversations,
        total_assistant_messages=total_assistant_messages,
        intent_distribution=[
            IntentCount(intent=intent, count=count)
            for intent, count in intent_counter.most_common()
        ],
        guardrail_violation_count=guardrail_violation_count,
        forced_refusal_count=forced_refusal_count,
        forced_refusal_rate=(
            forced_refusal_count / total_assistant_messages if total_assistant_messages else 0.0
        ),
        average_latency_ms=(sum(latencies) / len(latencies)) if latencies else None,
        feedback_thumbs_up=thumbs_up,
        feedback_thumbs_down=thumbs_down,
        feedback_response_rate=(
            rated / total_assistant_messages if total_assistant_messages else 0.0
        ),
    )
