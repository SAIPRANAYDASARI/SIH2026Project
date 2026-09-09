"""Translation adapter tests: `NoOpTranslationClient` directly, and
`BhashiniTranslationClient` against an `httpx.MockTransport` driving its
real wire format — no live Bhashini server."""

from __future__ import annotations

import json

import httpx
import pytest

from app.core.config import Settings
from app.translate.client import (
    BhashiniTranslationClient,
    NoOpTranslationClient,
    get_translation_client,
)


@pytest.mark.asyncio
async def test_noop_client_returns_text_unchanged() -> None:
    client = NoOpTranslationClient()
    result = await client.translate("Hello world", target_language="hi")
    assert result == "Hello world"


@pytest.mark.asyncio
async def test_bhashini_client_skips_call_for_english() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("should not call out for target_language='en'")

    settings = Settings(translation_backend="bhashini", bhashini_pipeline_id="pid")
    client = BhashiniTranslationClient(settings, transport=httpx.MockTransport(handler))
    result = await client.translate("Hello", target_language="en")
    assert result == "Hello"


@pytest.mark.asyncio
async def test_bhashini_client_parses_translation_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["pipelineTasks"][0]["config"]["language"]["targetLanguage"] == "hi"
        return httpx.Response(
            200,
            json={"pipelineResponse": [{"output": [{"target": "नमस्ते दुनिया"}]}]},
        )

    settings = Settings(
        translation_backend="bhashini",
        bhashini_api_key="key",
        bhashini_user_id="uid",
        bhashini_pipeline_id="pid",
    )
    client = BhashiniTranslationClient(settings, transport=httpx.MockTransport(handler))
    result = await client.translate("Hello world", target_language="hi")
    assert result == "नमस्ते दुनिया"


@pytest.mark.asyncio
async def test_bhashini_client_fails_safe_on_malformed_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    settings = Settings(translation_backend="bhashini", bhashini_pipeline_id="pid")
    client = BhashiniTranslationClient(settings, transport=httpx.MockTransport(handler))
    result = await client.translate("Hello world", target_language="hi")
    assert result == "Hello world"


def test_factory_returns_noop_by_default() -> None:
    settings = Settings(translation_backend="none")
    assert isinstance(get_translation_client(settings), NoOpTranslationClient)


def test_factory_returns_bhashini_when_configured() -> None:
    settings = Settings(translation_backend="bhashini")
    assert isinstance(get_translation_client(settings), BhashiniTranslationClient)
