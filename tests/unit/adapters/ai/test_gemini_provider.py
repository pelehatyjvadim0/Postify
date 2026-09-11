"""Gemini-провайдер на подставном транспорте: ключа нет, в сеть не ходим."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest

from postify.adapters.ai.gemini_provider import (
    EMBEDDING_MODEL,
    TEXT_MODEL,
    GeminiModelProvider,
)
from postify.application.ai.gateway import EMBEDDING_DIMENSIONS, ModelCallError


def _provider(handler):
    requests: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    client = httpx.Client(transport=httpx.MockTransport(recording))
    return GeminiModelProvider(client, api_key="test-key"), requests


def _text_response(text: str) -> httpx.Response:
    return httpx.Response(
        200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]}
    )


def test_requires_api_key() -> None:
    with pytest.raises(ModelCallError) as caught:
        GeminiModelProvider(httpx.Client(), api_key="  ")

    assert caught.value.code == "provider_not_configured"


def test_complete_posts_prompt_with_key_in_header_only() -> None:
    provider, requests = _provider(lambda request: _text_response("ответ"))

    assert provider.complete("напиши пост") == "ответ"
    request = requests[0]
    assert request.url == f"https://generativelanguage.googleapis.com/v1beta/models/{TEXT_MODEL}:generateContent"
    assert request.headers["x-goog-api-key"] == "test-key"
    assert "test-key" not in str(request.url)
    body = json.loads(request.content)
    assert body == {"contents": [{"parts": [{"text": "напиши пост"}]}]}
    assert provider.name == "gemini" and provider.model == TEXT_MODEL


def test_complete_with_schema_requests_structured_json() -> None:
    provider, requests = _provider(lambda request: _text_response('{"ok": true}'))
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}

    provider.complete("оцени", output_schema=schema, model="gemini-other")

    body = json.loads(requests[0].content)
    assert body["generationConfig"] == {
        "responseMimeType": "application/json",
        "responseSchema": schema,
    }
    assert requests[0].url.path.endswith("/models/gemini-other:generateContent")


def test_complete_joins_text_parts() -> None:
    provider, _ = _provider(
        lambda request: httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "a"}, {"text": "b"}]}}]},
        )
    )

    assert provider.complete("x") == "ab"


def test_caption_sends_inline_image(tmp_path: Path) -> None:
    image = tmp_path / "кот.png"
    image.write_bytes(b"\x89PNG-fake")
    provider, requests = _provider(lambda request: _text_response("Кот на подоконнике."))

    assert provider.caption_image(image) == "Кот на подоконнике."
    body = json.loads(requests[0].content)
    parts = body["contents"][0]["parts"]
    assert isinstance(parts[0]["text"], str) and parts[0]["text"]
    assert parts[1]["inline_data"] == {
        "mime_type": "image/png",
        "data": base64.b64encode(b"\x89PNG-fake").decode("ascii"),
    }


def test_caption_of_missing_file_is_invalid_output(tmp_path: Path) -> None:
    provider, requests = _provider(lambda request: _text_response("x"))

    with pytest.raises(ModelCallError) as caught:
        provider.caption_image(tmp_path / "нет.png")

    assert caught.value.code == "invalid_output"
    assert requests == []


def test_embed_requests_fixed_dimensionality_and_normalizes() -> None:
    raw = [3.0] + [0.0] * (EMBEDDING_DIMENSIONS - 2) + [4.0]
    provider, requests = _provider(
        lambda request: httpx.Response(200, json={"embedding": {"values": raw}})
    )

    vector = provider.embed("подпись к фото")

    request = requests[0]
    assert request.url.path.endswith(f"/models/{EMBEDDING_MODEL}:embedContent")
    body = json.loads(request.content)
    assert body["outputDimensionality"] == EMBEDDING_DIMENSIONS == 768
    assert body["content"] == {"parts": [{"text": "подпись к фото"}]}
    assert len(vector) == EMBEDDING_DIMENSIONS
    assert vector[0] == pytest.approx(0.6) and vector[-1] == pytest.approx(0.8)


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx.Response(429, json={"error": {"message": "quota"}}), "provider_unavailable"),
        (httpx.Response(500, text="oops"), "provider_unavailable"),
        (httpx.Response(200, content=b"not-json"), "invalid_output"),
        (httpx.Response(200, json=[]), "invalid_output"),
        (httpx.Response(200, json={"candidates": []}), "invalid_output"),
        (httpx.Response(200, json={"candidates": [{"content": {"parts": []}}]}), "invalid_output"),
    ],
)
def test_bad_responses_become_one_error_type(response: httpx.Response, code: str) -> None:
    provider, _ = _provider(lambda request: response)

    with pytest.raises(ModelCallError) as caught:
        provider.complete("x")

    assert caught.value.code == code
    assert "test-key" not in caught.value.reason


def test_transport_error_is_provider_unavailable() -> None:
    def failing(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("нет сети", request=request)

    provider, _ = _provider(failing)

    with pytest.raises(ModelCallError) as caught:
        provider.embed("x")

    assert caught.value.code == "provider_unavailable"


def test_embed_without_vector_is_invalid_output() -> None:
    provider, _ = _provider(lambda request: httpx.Response(200, json={"embedding": {}}))

    with pytest.raises(ModelCallError) as caught:
        provider.embed("x")

    assert caught.value.code == "invalid_output"
