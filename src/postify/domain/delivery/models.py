from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DeliveryStatus(StrEnum):
    SENDING = "sending"
    RETRYABLE = "retryable"
    PUBLISHED = "published"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


class PublishFailureKind(StrEnum):
    RETRYABLE = "retryable"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True, slots=True)
class DeliveryClaim:
    delivery_id: int
    package_id: int
    attempt_no: int
    post_text: str
    media_path: str
    media_mime: str


@dataclass(frozen=True, slots=True)
class TelegramMessage:
    message_id: int


@dataclass(frozen=True, slots=True)
class PublishContentResult:
    outcome: str
    package_id: int | None = None
    message_id: int | None = None


class TelegramPublishError(RuntimeError):
    def __init__(self, *, code: str, reason: str, kind: PublishFailureKind) -> None:
        if not isinstance(code, str) or not code.strip() or not isinstance(reason, str) or not reason.strip():
            raise ValueError("Код и причина ошибки обязательны")
        self.code = code
        self.reason = reason
        self.kind = PublishFailureKind(kind)
        super().__init__(reason)
