"""OpenRouter-провайдер на подставном транспорте: ключа нет, в сеть не ходим."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest

from postify.adapters.ai.openrouter_provider import (
    BASE_URL,
    EMBEDDING_MODEL,
    TEXT_MODEL,
    OpenRouterModelProvider,
)
from postify.application.ai.gateway import EMBEDDING_DIMENSIONS, ModelCallError


def _provider(handler):
    requests: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    client = httpx.Client(transport=httpx.MockTransport(recording))
    return OpenRouterModelProvider(client, api_key="test-key"), requests


def _text_response(text: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


def test_requires_api_key() -> None:
    with pytest.raises(ModelCallError) as caught:
        OpenRouterModelProvider(httpx.Client(), api_key="  ")

    assert caught.value.code == "provider_not_configured"


def test_complete_posts_prompt_with_key_in_header_only() -> None:
    provider, requests = _provider(lambda request: _text_response("ответ"))

    assert provider.complete("напиши пост") == "ответ"
    request = requests[0]
    assert str(request.url) == f"{BASE_URL}/chat/completions"
    assert request.headers["authorization"] == "Bearer test-key"
    assert "test-key" not in str(request.url)
    assert json.loads(request.content) == {
        "model": TEXT_MODEL,
        "messages": [{"role": "user", "content": "напиши пост"}],
    }
    assert provider.name == "openrouter" and provider.model == TEXT_MODEL


def test_complete_with_schema_requests_structured_json() -> None:
    provider, requests = _provider(lambda request: _text_response('{"ok": true}'))
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}

    provider.complete("оцени", output_schema=schema, model="other/model")

    body = json.loads(requests[0].content)
    assert body["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "output", "strict": True, "schema": schema},
    }
    assert body["model"] == "other/model"


def test_known_reasoning_effort_is_translated() -> None:
    provider, requests = _provider(lambda request: _text_response("ответ"))

    provider.complete("думай", reasoning_effort="high")

    assert json.loads(requests[0].content)["reasoning"] == {"effort": "high"}


@pytest.mark.parametrize("effort", [None, "none", "ультра"])
def test_unknown_reasoning_effort_is_not_sent(effort: str | None) -> None:
    provider, requests = _provider(lambda request: _text_response("ответ"))

    provider.complete("думай", reasoning_effort=effort)

    assert "reasoning" not in json.loads(requests[0].content)


def test_caption_sends_data_url_with_mime(tmp_path: Path) -> None:
    image = tmp_path / "кот.png"
    image.write_bytes(b"\x89PNG-fake")
    provider, requests = _provider(lambda request: _text_response("Кот на подоконнике."))

    assert provider.caption_image(image) == "Кот на подоконнике."
    body = json.loads(requests[0].content)
    assert str(requests[0].url) == f"{BASE_URL}/chat/completions"
    assert body["model"] == TEXT_MODEL
    content = body["messages"][0]["content"]
    assert content[0]["type"] == "text" and content[0]["text"]
    encoded = base64.b64encode(b"\x89PNG-fake").decode("ascii")
    assert content[1] == {
        "type": "image_url",
        "image_url": {"url": f"data:image/png;base64,{encoded}"},
    }


def test_caption_of_jpeg_uses_its_own_mime(tmp_path: Path) -> None:
    image = tmp_path / "фото.jpg"
    image.write_bytes(b"\xff\xd8jpeg")
    provider, requests = _provider(lambda request: _text_response("Фото."))

    provider.caption_image(image)

    url = json.loads(requests[0].content)["messages"][0]["content"][1]["image_url"]["url"]
    assert url.startswith("data:image/jpeg;base64,")


def test_caption_of_missing_file_is_invalid_output(tmp_path: Path) -> None:
    provider, requests = _provider(lambda request: _text_response("x"))

    with pytest.raises(ModelCallError) as caught:
        provider.caption_image(tmp_path / "нет.png")

    assert caught.value.code == "invalid_output"
    assert requests == []


def test_embed_requests_fixed_dimensionality_and_normalizes() -> None:
    raw = [3.0] + [0.0] * (EMBEDDING_DIMENSIONS - 2) + [4.0]
    provider, requests = _provider(
        lambda request: httpx.Response(200, json={"data": [{"embedding": raw}]})
    )

    vector = provider.embed("подпись к фото")

    request = requests[0]
    assert str(request.url) == f"{BASE_URL}/embeddings"
    body = json.loads(request.content)
    assert body == {
        "model": EMBEDDING_MODEL,
        "input": "подпись к фото",
        "encoding_format": "float",
        "dimensions": EMBEDDING_DIMENSIONS,
    }
    assert body["dimensions"] == 768
    assert len(vector) == EMBEDDING_DIMENSIONS
    assert vector[0] == pytest.approx(0.6) and vector[-1] == pytest.approx(0.8)
    assert sum(value * value for value in vector) == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx.Response(401, json={"error": {"message": "no credits"}}), "provider_unavailable"),
        (httpx.Response(429, json={"error": {"message": "rate limit"}}), "provider_unavailable"),
        (httpx.Response(500, text="oops"), "provider_unavailable"),
        (httpx.Response(200, content=b"not-json"), "invalid_output"),
        (httpx.Response(200, json=[]), "invalid_output"),
        (httpx.Response(200, json={"choices": []}), "invalid_output"),
        (httpx.Response(200, json={"error": {"message": "moderation"}}), "invalid_output"),
        (httpx.Response(200, json={"choices": [{"message": {"content": " "}}]}), "invalid_output"),
    ],
)
def test_bad_responses_become_one_error_type(response: httpx.Response, code: str) -> None:
    provider, _ = _provider(lambda request: response)

    with pytest.raises(ModelCallError) as caught:
        provider.complete("x")

    assert caught.value.code == code
    assert "test-key" not in caught.value.reason
    assert "test-key" not in str(caught.value)


def test_transport_error_is_provider_unavailable() -> None:
    def failing(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("нет сети", request=request)

    provider, _ = _provider(failing)

    with pytest.raises(ModelCallError) as caught:
        provider.embed("x")

    assert caught.value.code == "provider_unavailable"
    assert "test-key" not in caught.value.reason


def test_embed_without_vector_is_invalid_output() -> None:
    provider, _ = _provider(lambda request: httpx.Response(200, json={"data": []}))

    with pytest.raises(ModelCallError) as caught:
        provider.embed("x")

    assert caught.value.code == "invalid_output"


def test_embed_of_zero_vector_is_invalid_output() -> None:
    zero = [0.0] * EMBEDDING_DIMENSIONS
    provider, _ = _provider(
        lambda request: httpx.Response(200, json={"data": [{"embedding": zero}]})
    )

    with pytest.raises(ModelCallError) as caught:
        provider.embed("x")

    assert caught.value.code == "invalid_output"


def test_models_are_configurable() -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda request: _text_response("x")))
    provider = OpenRouterModelProvider(
        client, api_key="k", model="vendor/text", embedding_model="vendor/embed"
    )

    assert provider.model == "vendor/text"
    assert provider.embedding_model == "vendor/embed"
