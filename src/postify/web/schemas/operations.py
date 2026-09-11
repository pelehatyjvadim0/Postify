"""Схемы журнала операций и публикаций — разделы 1 и 11 контракта API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from postify.web.schemas.common import ResponseSchema


class OperationErrorResponse(ResponseSchema):
    code: str
    message: str


class AcceptedOperationResponse(ResponseSchema):
    """Ответ 202 на длительную операцию: по нему фронтенд начинает поллинг."""

    operation_id: int
    status: Literal["running"] = "running"


class OperationResponse(ResponseSchema):
    operation_id: int
    purpose: str
    status: str
    # Автор действия — владелец проекта либо планировщик.
    actor: Literal["user", "scheduler"]
    mode: str
    outcome: str | None
    result: dict[str, Any]
    error: OperationErrorResponse | None
    started_at: datetime
    finished_at: datetime | None


class PublicationAttemptResponse(ResponseSchema):
    attempt_no: int
    outcome: str
    code: str | None
    reason: str | None
    message_id: int | None
    started_at: datetime
    finished_at: datetime


class PublicationResponse(ResponseSchema):
    delivery_id: int
    post_id: int
    provider: str | None
    status: str
    attempt_count: int
    message_id: int | None
    failure_code: str | None
    failure_reason: str | None
    sending_started_at: datetime
    confirmed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    attempts: tuple[PublicationAttemptResponse, ...]
