from __future__ import annotations

from pathlib import Path

import httpx
import pytest


TOKEN = "123456:SENTINEL-TOKEN"
CHAT_ID = "-100123456789"
CAPTION = "Секретный текст поста"
PNG_BYTES = b"\x89PNG\r\n\x1a\nSENTINEL-FILE-BYTES"


def _api():
    from postify.adapters.telegram.bot_api import TelegramBotApiPublisher
    from postify.domain.delivery.models import (
        DeliveryClaim,
        PublishFailureKind,
        TelegramMessage,
        TelegramPublishError,
    )

    return TelegramBotApiPublisher, DeliveryClaim, PublishFailureKind, TelegramMessage, TelegramPublishError


def _claim(DeliveryClaim, media_path: Path):
    return DeliveryClaim(11, 41, 1, CAPTION, str(media_path), "image/png")


def _publisher(TelegramBotApiPublisher, handler):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return client, TelegramBotApiPublisher(client, bot_token=TOKEN, chat_id=CHAT_ID)


def test_send_photo_uses_exact_endpoint_and_multipart_contract(tmp_path: Path) -> None:
    # Поломка: неверный endpoint/field/MIME/basename/байты делают пост непригодным.
    Publisher, DeliveryClaim, _, TelegramMessage, _ = _api()
    media = tmp_path / "telegram-card.png"
    media.write_bytes(PNG_BYTES)

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read()
        content_type = request.headers["content-type"]
        assert request.method == "POST"
        assert request.url.path == f"/bot{TOKEN}/sendPhoto"
        assert content_type.startswith("multipart/form-data; boundary=")
        assert b'name="chat_id"' in body and CHAT_ID.encode() in body
        assert b'name="caption"' in body and CAPTION.encode() in body
        assert b'name="photo"; filename="telegram-card.png"' in body
        assert b"Content-Type: image/png" in body
        assert PNG_BYTES in body
        assert b"parse_mode" not in body
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 731}})

    client, publisher = _publisher(Publisher, handler)
    try:
        result = publisher.publish(_claim(DeliveryClaim, media))
    finally:
        client.close()

    assert result == TelegramMessage(731)


@pytest.mark.parametrize(
    ("payload", "expected_kind"),
    [
        ({"ok": False, "error_code": 429, "description": "rate; SENTINEL-TOKEN"}, "retryable"),
        ({"ok": False, "error_code": 503, "description": "upstream"}, "retryable"),
        ({"ok": False, "error_code": 400, "description": "bad chat"}, "failed"),
    ],
)
def test_ok_false_is_classified_without_leaking_response_or_request(
    tmp_path: Path, payload: dict[str, object], expected_kind: str
) -> None:
    # Поломка: 429/5xx становятся terminal или Telegram response утекает в exception.
    Publisher, DeliveryClaim, FailureKind, _, PublishError = _api()
    media = tmp_path / "card.png"
    media.write_bytes(PNG_BYTES)
    client, publisher = _publisher(Publisher, lambda request: httpx.Response(200, json=payload))

    try:
        with pytest.raises(PublishError) as caught:
            publisher.publish(_claim(DeliveryClaim, media))
    finally:
        client.close()

    error = caught.value
    assert error.kind is FailureKind(expected_kind)
    assert error.code == ("telegram_retryable" if expected_kind == "retryable" else "telegram_rejected")
    _assert_safe_error(error)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json={"ok": True, "result": {}}),
        httpx.Response(200, json={"ok": True, "result": {"message_id": "731"}}),
        httpx.Response(200, json={"ok": True, "result": {"message_id": True}}),
    ],
)
def test_malformed_success_is_uncertain_and_never_accepted(
    tmp_path: Path, response: httpx.Response
) -> None:
    # Поломка: malformed/missing/non-int message_id считается confirmation.
    Publisher, DeliveryClaim, FailureKind, _, PublishError = _api()
    media = tmp_path / "card.png"
    media.write_bytes(PNG_BYTES)
    client, publisher = _publisher(Publisher, lambda request: response)

    try:
        with pytest.raises(PublishError) as caught:
            publisher.publish(_claim(DeliveryClaim, media))
    finally:
        client.close()

    assert caught.value.kind is FailureKind.UNCERTAIN
    assert caught.value.code == "telegram_invalid_response"
    _assert_safe_error(caught.value)


def test_file_error_before_request_is_retryable_and_makes_no_http_call(tmp_path: Path) -> None:
    # Поломка: pre-request filesystem error помечается uncertain или всё же делает HTTP.
    Publisher, DeliveryClaim, FailureKind, _, PublishError = _api()
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 731}})

    client, publisher = _publisher(Publisher, handler)
    try:
        with pytest.raises(PublishError) as caught:
            publisher.publish(_claim(DeliveryClaim, tmp_path / "missing.png"))
    finally:
        client.close()

    assert calls == []
    assert caught.value.kind is FailureKind.RETRYABLE
    assert caught.value.code == "media_unavailable"
    _assert_safe_error(caught.value)


def test_transport_timeout_after_request_is_uncertain(tmp_path: Path) -> None:
    # Поломка: timeout автоматически ретраится и создаёт дубль.
    Publisher, DeliveryClaim, FailureKind, _, PublishError = _api()
    media = tmp_path / "card.png"
    media.write_bytes(PNG_BYTES)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout at " + str(request.url), request=request)

    client, publisher = _publisher(Publisher, handler)
    try:
        with pytest.raises(PublishError) as caught:
            publisher.publish(_claim(DeliveryClaim, media))
    finally:
        client.close()

    assert caught.value.kind is FailureKind.UNCERTAIN
    assert caught.value.code == "telegram_transport_uncertain"
    _assert_safe_error(caught.value)


def _assert_safe_error(error: Exception) -> None:
    rendered = str(error)
    assert TOKEN not in rendered
    assert "api.telegram.org" not in rendered
    assert "/sendPhoto" not in rendered
    assert CAPTION not in rendered
    assert PNG_BYTES.decode("latin1") not in rendered


def test_text_only_post_uses_send_message_with_exact_text():
    from urllib.parse import parse_qs
    Publisher, Claim, _, _, _ = _api()
    requests = []
    def handler(request):
        requests.append(request)
        assert request.url.path == f"/bot{TOKEN}/sendMessage"
        assert parse_qs(request.read().decode()) == {"chat_id": [CHAT_ID], "text": [CAPTION]}
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 912}})
    client, publisher = _publisher(Publisher, handler)
    try:
        assert publisher.publish(Claim(1, 2, 1, CAPTION, None, None)).message_id == 912
    finally:
        client.close()
    assert len(requests) == 1
