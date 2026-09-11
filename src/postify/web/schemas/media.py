"""Схемы пула изображений — раздел 10 контракта API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from postify.web.schemas.common import RequestSchema, ResponseSchema


class MediaPatchRequest(RequestSchema):
    """Ручная правка: подпись и участие в подборе."""

    caption: str | None = Field(default=None, max_length=2000)
    enabled: bool | None = None

    @model_validator(mode="after")
    def at_least_one_change(self) -> "MediaPatchRequest":
        if not self.model_fields_set:
            raise ValueError("Нечего менять: укажите подпись или флаг включения")
        return self


class MediaAssetResponse(ResponseSchema):
    """Изображение пула.

    ``caption_model`` сверх контракта: пока подписи делает заглушка, UI обязан
    показывать это честно — ``mock`` означает, что подпись не описывает
    содержимое снимка.
    """

    id: int
    url: str
    thumb_url: str
    mime: str
    caption: str | None
    caption_status: Literal["pending", "ready", "failed"]
    caption_model: str | None
    width: int
    height: int
    bytes: int
    enabled: bool
    use_count: int
    uploaded_at: datetime
    last_used_at: datetime | None
    available: bool


class MediaPageResponse(ResponseSchema):
    """Страница пула с курсором на следующую."""

    items: tuple[MediaAssetResponse, ...]
    next_cursor: str | None
