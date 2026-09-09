"""Pluggable translation adapter (Step 10), same shape as `app.llm.client`'s
adapter (decision #3): one interface, switchable backend, chosen by
`translation_backend`.

- `NoOpTranslationClient` — the default (`translation_backend="none"`):
  returns the text unchanged. This is also the fallback for
  `target_language in (None, "en")`, so a monolingual English deployment
  (or the fully offline mode from Step 13) never needs network egress for
  this at all.
- `BhashiniTranslationClient` — calls the Bhashini pipeline (India's
  government multilingual API, https://bhashini.gov.in) via its
  compute/pipeline HTTP API. Requires `bhashini_api_key`/`bhashini_user_id`/
  `bhashini_pipeline_id` — see `.env.example`; the original build brief
  says to ask the user for this key rather than inventing or committing one.

Translation is applied only to the *final*, already-guardrail-checked
answer text (see `app/api/v1/chat.py`) — never to the streamed token
deltas, and never to the retrieval/citation pipeline, which stays
English-only. This is a scope decision, not an oversight: token-by-token
machine translation mid-stream would either block streaming entirely or
require re-translating a growing prefix on every token, and citation
markers (`[N]`) need to survive translation intact, which is far more
reliable to check once against the complete text. See docs/DECISIONS.md,
Step 10.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import httpx

from app.core.config import Settings, get_settings


class TranslationClient(ABC):
    @abstractmethod
    async def translate(self, text: str, *, target_language: str) -> str:
        """Translate `text` into `target_language` (an ISO 639-1 code,
        e.g. "hi", "ta", "bn"). Implementations must be safe to call with
        `target_language == "en"` (should short-circuit to `text`)."""


class NoOpTranslationClient(TranslationClient):
    async def translate(self, text: str, *, target_language: str) -> str:  # noqa: ARG002
        return text


class BhashiniTranslationClient(TranslationClient):
    """Calls Bhashini's ULCA pipeline compute API.

    Bhashini's real integration is a two-step handshake (a "pipeline
    config" call to discover the right underlying model/service id for a
    language pair, then a "compute" call to actually translate) behind an
    inference-authorization header. This implementation does the compute
    call directly against a pre-selected `bhashini_pipeline_id`
    (obtained once via the Bhashini dashboard for the language pairs this
    deployment supports) rather than re-discovering it on every request,
    to keep the request path to one HTTP call.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._transport = transport

    async def translate(self, text: str, *, target_language: str) -> str:
        if target_language == "en" or not text.strip():
            return text

        settings = self._settings
        url = f"{settings.bhashini_base_url}/pipeline/inference"
        payload = {
            "pipelineTasks": [
                {
                    "taskType": "translation",
                    "config": {
                        "language": {"sourceLanguage": "en", "targetLanguage": target_language},
                        "serviceId": settings.bhashini_pipeline_id,
                    },
                }
            ],
            "inputData": {"input": [{"source": text}]},
        }
        headers = {
            "Authorization": settings.bhashini_api_key,
            "userID": settings.bhashini_user_id,
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(transport=self._transport, timeout=15.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        try:
            return str(
                data["pipelineResponse"][0]["output"][0]["target"],
            )
        except (KeyError, IndexError, TypeError):
            # Malformed/unexpected Bhashini response — fail safe to the
            # original English text rather than raising and losing the
            # already-generated, already-cited answer.
            return text


def get_translation_client(settings: Settings | None = None) -> TranslationClient:
    settings = settings or get_settings()
    if settings.translation_backend == "bhashini":
        return BhashiniTranslationClient(settings)
    return NoOpTranslationClient()
