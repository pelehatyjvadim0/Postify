"""Схемы постов — раздел 8 контракта API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field, model_validator

from postify.web.schemas.common import RequestSchema, ResponseSchema


class PostPatchRequest(RequestSchema):
    """Правка текста или изображения поста редактором."""

    post_text: str | None = Field(default=None, min_length=1, max_length=4096)
    media_asset_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def at_least_one_change(self) -> "PostPatchRequest":
        if not self.model_fields_set:
            raise ValueError("Нечего менять: укажите текст или изображение")
        return self


class PostMediaResponse(ResponseSchema):
    asset_id: int
    caption: str
    url: str
    rationale: str
    last_used_at: datetime | None


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
    slot_id: int
    status: str
    title: str
    excerpt: str
    publish_at: datetime
    rubric: dict[str, Any] | None
    checks_summary: dict[str, Any]


class PublishedResponse(ResponseSchema):
    published_at: datetime
    message_url: str


class PostResponse(ResponseSchema):
    """Карточка поста с результатами генерации и проверок."""

    id: int
    slot_id: int | None
    status: str
    post_text: str
    char_count: int
    media: PostMediaResponse | None
    generation: dict[str, Any] | None
    validation: dict[str, Any]
    delivery: PostDeliveryResponse | None
    published: PublishedResponse | None
    history: tuple[PostHistoryResponse, ...]
    created_at: datetime
    updated_at: datetime
