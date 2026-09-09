"""The chat endpoint: streams a grounded, cited answer over Server-Sent
Events while persisting both the user's message and the assistant's final
answer — Step 6's "FastAPI surface + persistence" scope, built directly on
top of Step 5's `app.answer.engine`.

Three SSE event types, in order:

- `conversation` — sent once, immediately, carrying the (possibly newly
  created) conversation id, before any LLM output exists yet.
- `token` — zero or more, each carrying one text delta as the LLM
  generates it.
- `final` — exactly one, carrying the guardrail-redacted final text's
  metadata (citations, invalid markers, guardrail actions, intent, model,
  latency) and the persisted message id. The frontend (Step 7) should
  treat concatenated `token` events as provisional and defer to `final` for
  the authoritative text and citations.
- `error` — instead of `final`, if anything failed after streaming had
  already started (so a plain HTTP error status is no longer possible).

See `GET /conversations` and `GET /conversations/{id}/messages` for reading
back persisted history, scoped to the caller's signed session cookie
(`app.core.session`) — there is no login yet, only anonymous per-browser
history.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator, Iterable

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.answer.citations import Citation
from app.answer.engine import FinalEvent, TokenEvent, stream_answer
from app.core.config import Settings, get_settings
from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.core.session import decode_session_cookie, encode_session_cookie, new_session_id
from app.db.session import AsyncSessionLocal, get_db
from app.models.conversation import Conversation, Message, MessageRole
from app.schemas.analytics import FeedbackRequest
from app.schemas.chat import ChatRequest, ConversationSchema, MessageSchema
from app.services import conversation_service

SUPPORTED_LANGUAGES = {"en", "hi"}

logger = get_logger(__name__)
router = APIRouter(tags=["chat"])

SESSION_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 30  # 30 days


def _resolve_session_id(cookie_value: str | None, settings: Settings) -> str:
    if cookie_value:
        decoded = decode_session_cookie(cookie_value, settings.app_secret_key)
        if decoded:
            return decoded
    return new_session_id()


def _require_session_id(cookie_value: str | None, settings: Settings) -> str:
    session_id = (
        decode_session_cookie(cookie_value, settings.app_secret_key) if cookie_value else None
    )
    if session_id is None:
        raise NotFoundError("No session cookie — nothing has been saved for this browser yet.")
    return session_id


def _sse_event(event: str, data: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _citations_payload(citations: Iterable[Citation]) -> list[dict[str, object]]:
    return [
        {
            "marker": c.marker,
            "chunk_id": c.chunk_id,
            "is_number": c.is_number,
            "clause_number": c.clause_number,
            "document_title": c.document_title,
            "document_source_url": c.document_source_url,
        }
        for c in citations
    ]


@router.post("/chat")
async def chat(payload: ChatRequest, request: Request) -> StreamingResponse:
    settings = get_settings()
    cookie_value = request.cookies.get(settings.session_cookie_name)
    session_id = _resolve_session_id(cookie_value, settings)

    async def event_stream() -> AsyncGenerator[str, None]:
        # This generator opens and closes its own session rather than using
        # `Depends(get_db)`: FastAPI closes a `yield`-based dependency as
        # soon as this endpoint function *returns* the StreamingResponse
        # object, which happens before the response body has actually been
        # sent — a session from `Depends(get_db)` would already be closed
        # by the time this generator runs. See docs/DECISIONS.md, Step 6.
        async with AsyncSessionLocal() as db_session:
            try:
                conversation = await conversation_service.get_or_create_conversation(
                    db_session,
                    session_id=session_id,
                    conversation_id=payload.conversation_id,
                    audience=payload.audience,
                )
                await conversation_service.persist_message(
                    db_session,
                    conversation_id=conversation.id,
                    role=MessageRole.USER,
                    content=payload.message,
                )
                # Title the thread from its opening question so the history
                # sidebar has something to show; no-op on follow-up turns.
                await conversation_service.set_title_from_first_message(
                    db_session, conversation=conversation, first_message=payload.message
                )
                await db_session.commit()

                yield _sse_event("conversation", {"conversation_id": str(conversation.id)})

                target_language = (
                    payload.target_language
                    if payload.target_language in SUPPORTED_LANGUAGES
                    else "en"
                )

                async for event in stream_answer(
                    db_session,
                    payload.message,
                    audience=conversation.audience,
                    target_language=target_language,
                    settings=settings,
                ):
                    if isinstance(event, TokenEvent):
                        yield _sse_event("token", {"text": event.text})
                    elif isinstance(event, FinalEvent):
                        result = event.result
                        citations_payload = _citations_payload(result.citations)
                        message = await conversation_service.persist_message(
                            db_session,
                            conversation_id=conversation.id,
                            role=MessageRole.ASSISTANT,
                            content=result.text,
                            intent=result.query_analysis.intent.value,
                            citations=citations_payload,
                            retrieval_debug={
                                "chunk_ids": [str(c.chunk_id) for c in result.chunks],
                                "invalid_citation_markers": result.invalid_citation_markers,
                                "guardrail_violations": result.guardrail_violations,
                                "forced_refusal": result.forced_refusal,
                            },
                            model_backend=result.model_backend,
                            latency_ms=result.latency_ms,
                        )
                        await db_session.commit()
                        yield _sse_event(
                            "final",
                            {
                                "message_id": str(message.id),
                                "conversation_id": str(conversation.id),
                                "citations": citations_payload,
                                "invalid_citation_markers": result.invalid_citation_markers,
                                "guardrail_violations": result.guardrail_violations,
                                "intent": result.query_analysis.intent.value,
                                "model_backend": result.model_backend,
                                "latency_ms": result.latency_ms,
                                "forced_refusal": result.forced_refusal,
                                "target_language": target_language,
                            },
                        )
            except NotFoundError as exc:
                await db_session.rollback()
                yield _sse_event("error", {"detail": exc.detail})
            except httpx.HTTPError as exc:
                # An upstream model/inference call failed even after the
                # adapter's own retries (see app.llm.client) — that's an
                # outage on the provider's side, not a bug here, so say so
                # rather than showing a generic internal-failure message the
                # user can't act on.
                await db_session.rollback()
                logger.warning(
                    "chat_stream_upstream_failed", session_id=session_id, error=str(exc)
                )
                yield _sse_event(
                    "error",
                    {
                        "detail": (
                            "The language model provider is temporarily unavailable "
                            "(it failed several retries). This is an upstream outage, "
                            "not a problem with your question — please try again in a moment."
                        )
                    },
                )
            except Exception:
                await db_session.rollback()
                logger.exception("chat_stream_failed", session_id=session_id)
                yield _sse_event(
                    "error",
                    {"detail": "The answer engine failed unexpectedly. Please try again."},
                )

    response = StreamingResponse(event_stream(), media_type="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"  # nginx must not buffer SSE (Step 13)
    response.set_cookie(
        settings.session_cookie_name,
        encode_session_cookie(session_id, settings.app_secret_key),
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        max_age=SESSION_COOKIE_MAX_AGE_SECONDS,
    )
    return response


@router.get("/conversations", response_model=list[ConversationSchema])
async def list_conversations(
    request: Request,
    settings: Settings = Depends(get_settings),
    db_session: AsyncSession = Depends(get_db),
) -> list[Conversation]:
    cookie_value = request.cookies.get(settings.session_cookie_name)
    session_id = (
        decode_session_cookie(cookie_value, settings.app_secret_key) if cookie_value else None
    )
    if session_id is None:
        return []
    return await conversation_service.list_conversations(db_session, session_id)


@router.patch("/conversations/{conversation_id}/messages/{message_id}/feedback")
async def submit_feedback(
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    payload: FeedbackRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
    db_session: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    cookie_value = request.cookies.get(settings.session_cookie_name)
    session_id = _require_session_id(cookie_value, settings)
    await conversation_service.get_conversation_for_session(
        db_session, conversation_id=conversation_id, session_id=session_id
    )
    await conversation_service.record_feedback(
        db_session, message_id=message_id, rating=payload.rating, comment=payload.comment
    )
    await db_session.commit()
    return {"status": "ok"}


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageSchema])
async def list_conversation_messages(
    conversation_id: uuid.UUID,
    request: Request,
    settings: Settings = Depends(get_settings),
    db_session: AsyncSession = Depends(get_db),
) -> list[Message]:
    cookie_value = request.cookies.get(settings.session_cookie_name)
    session_id = _require_session_id(cookie_value, settings)
    await conversation_service.get_conversation_for_session(
        db_session, conversation_id=conversation_id, session_id=session_id
    )
    return await conversation_service.list_messages(db_session, conversation_id)
