import json

import httpx
import pytest

from postify.adapters.ai.gemini_content_analyzer import GeminiAnalysisError, GeminiContentAnalyzer
from postify.application.ports.content_analyzer import GenerationBrief
from postify.domain.content.models import AnalysisInput


MATERIAL = AnalysisInput(7, "", "خبر", "افتتحت المكتبة يوم 12 مايو وفيها 300 كتاب.")
POST = {"attempt_id": 7, "analysis": "Сохранены дата и число книг.", "post_text": "Библиотека открылась 12 мая. В ней 300 книг."}


def envelope(post=POST):
    return {"status": "completed", "steps": [{"type": "thought", "signature": "ignored"}, {"type": "model_output", "content": [{"type": "text", "text": json.dumps({"topics": [post]}, ensure_ascii=False)}]}]}


def test_gemini_transmits_original_and_brief_and_validates_russian_post():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=envelope())
    brief = GenerationBrief("Культура", "ru", "Читатели", "До 500 знаков", "")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        batch = GeminiContentAnalyzer(client=client, api_key="test-key").analyze([MATERIAL], 1, brief)
    assert batch.selected_topics[0].post_text == POST["post_text"]
    assert batch.selected_topics[0].media_query is None
    assert batch.requested_attempt_ids == (7,)
    request = requests[0]
    assert str(request.url) == "https://generativelanguage.googleapis.com/v1beta/interactions"
    assert request.headers["x-goog-api-key"] == "test-key"
    payload = json.loads(request.content)
    assert payload["model"] == "gemini-3.8-flash"
    assert payload["store"] is False
    data = json.loads(payload["input"])
    assert data["materials"][0]["text"] == MATERIAL.text
    assert data["brief"]["audience"] == "Читатели"
    assert data["brief"]["language"] == "ru"
    assert payload["response_format"]["mime_type"] == "application/json"


@pytest.mark.parametrize("payload", [
    {}, {"status": "in_progress", "steps": []},
    {"status": "completed", "steps": []},
    envelope({**POST, "post_text": "  "}),
    envelope({**POST, "post_text": "Arabic only text"}),
    envelope({**POST, "attempt_id": 99}),
    envelope({**POST, "attempt_id": "7"}),
    envelope({**POST, "post_text": "я" + "😀" * 2048}),
    envelope({**POST, "extra": "invented"}),
])
def test_invalid_or_incomplete_output_never_becomes_a_post(payload):
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))) as client:
        with pytest.raises(GeminiAnalysisError, match="^gemini_output_invalid$"):
            GeminiContentAnalyzer(client=client, api_key="test-key").analyze([MATERIAL], 1)


@pytest.mark.parametrize("status,code", [(403, "gemini_access_denied"), (429, "gemini_rate_limited"), (500, "gemini_unavailable")])
def test_http_failure_returns_safe_code_without_provider_body(status, code):
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(status, text="private-provider-detail"))) as client:
        with pytest.raises(GeminiAnalysisError) as caught:
            GeminiContentAnalyzer(client=client, api_key="test-key").analyze([MATERIAL], 1)
    assert caught.value.code == code
    assert "private-provider-detail" not in str(caught.value)


def test_timeout_is_not_a_successful_empty_result():
    def timeout(request):
        raise httpx.ReadTimeout("private-transport-detail", request=request)
    with httpx.Client(transport=httpx.MockTransport(timeout)) as client:
        with pytest.raises(GeminiAnalysisError, match="^gemini_timeout$"):
            GeminiContentAnalyzer(client=client, api_key="test-key").analyze([MATERIAL], 1)


def test_missing_key_makes_no_external_request():
    requests = []
    with httpx.Client(transport=httpx.MockTransport(lambda request: requests.append(request))) as client:
        with pytest.raises(GeminiAnalysisError, match="^gemini_not_configured$"):
            GeminiContentAnalyzer(client=client, api_key="").analyze([MATERIAL], 1)
    assert requests == []
