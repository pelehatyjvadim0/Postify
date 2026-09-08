from __future__ import annotations

from pathlib import Path

import httpx

from postify.domain.delivery.models import PublishFailureKind, TelegramMessage, TelegramPublishError


class TelegramBotApiPublisher:
    def __init__(self, client: httpx.Client, *, bot_token: str, chat_id: str) -> None:
        self.client = client
        self._url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
        self._text_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self.chat_id = chat_id

    def publish(self, claim):
        try:
            if claim.media_path:
                with Path(claim.media_path).open("rb") as stream:
                    response = self.client.post(self._url, data={"chat_id": self.chat_id, "caption": claim.post_text}, files={"photo": (Path(claim.media_path).name, stream, claim.media_mime)})
            else:
                response = self.client.post(self._text_url, data={"chat_id": self.chat_id, "text": claim.post_text})
        except OSError:
            raise TelegramPublishError(code="media_unavailable", reason="Локальное медиа недоступно", kind=PublishFailureKind.RETRYABLE) from None
        except (httpx.TimeoutException, httpx.TransportError):
            raise TelegramPublishError(code="telegram_transport_uncertain", reason="Не подтверждён ответ Telegram", kind=PublishFailureKind.UNCERTAIN) from None
        try:
            payload = response.json()
        except (ValueError, TypeError):
            raise TelegramPublishError(code="telegram_invalid_response", reason="Некорректный ответ Telegram", kind=PublishFailureKind.UNCERTAIN) from None
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            status = payload.get("error_code") if isinstance(payload, dict) else None
            kind = PublishFailureKind.RETRYABLE if type(status) is int and (status == 429 or status >= 500) else PublishFailureKind.FAILED
            code = "telegram_retryable" if kind is PublishFailureKind.RETRYABLE else "telegram_rejected"
            raise TelegramPublishError(code=code, reason="Telegram отклонил публикацию", kind=kind)
        result = payload.get("result")
        message_id = result.get("message_id") if isinstance(result, dict) else None
        if type(message_id) is not int or message_id <= 0:
            raise TelegramPublishError(code="telegram_invalid_response", reason="Некорректный ответ Telegram", kind=PublishFailureKind.UNCERTAIN)
        return TelegramMessage(message_id)
