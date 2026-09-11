"""Схемы постов — раздел 8 контракта API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field, field_validator, model_validator

from postify.web.schemas.common import RequestSchema, ResponseSchema


class PostPatchRequest(RequestSchema):
    """Правка поста редактором.

    ``scheduled_at`` живёт здесь временно: пока нет слотов контент-плана,
    время публикации задаётся прямо у поста. С появлением слотов оно уедет в
    ``PATCH /plan/{slot_id}``.
    """

    post_text: str | None = Field(default=None, min_length=1, max_length=4096)
    scheduled_at: datetime | None = None

    @field_validator("scheduled_at")
    @classmethod
    def aware_schedule(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Укажите часовой пояс времени публикации")
        return value

    @model_validator(mode="after")
    def at_least_one_change(self) -> "PostPatchRequest":
        if not self.model_fields_set:
            raise ValueError("Нечего менять: укажите текст или время публикации")
        return self


class PostMediaResponse(ResponseSchema):
    """Картинка поста. Пул изображений принесёт свой ``asset_id`` отдельно."""

    url: str
    mime: str | None = None


class PostHistoryResponse(ResponseSchema):
    status: str
    reason: str | None
    created_at: datetime


class PostDeliveryResponse(ResponseSchema):
    status: str
    message_id: int | None = None
    failure_code: str | None = None
    failure_reason: str | None = None
    published_at: datetime | None = None


class PostSummaryResponse(ResponseSchema):
    id: int
    status: str
    excerpt: str
    char_count: int
    media_available: bool
    scheduled_at: datetime | None
    delivery_status: str | None
    created_at: datetime
    updated_at: datetime


class PostResponse(ResponseSchema):
    """Карточка поста.

    ``slot_id`` и ``validation`` остаются пустыми до треков контент-плана и
    слоёв проверок: контракт их объявляет, данных за ними пока нет.
    """

    id: int
    slot_id: int | None
    status: str
    post_text: str
    char_count: int
    scheduled_at: datetime | None
    media: PostMediaResponse | None
    generation: dict[str, Any]
    validation: dict[str, Any] | None
    delivery: PostDeliveryResponse | None
    published: datetime | None
    history: tuple[PostHistoryResponse, ...]
    created_at: datetime
    updated_at: datetime
