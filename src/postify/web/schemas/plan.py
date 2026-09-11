"""Схемы контент-плана — раздел 7 контракта API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field, field_validator, model_validator

from postify.web.schemas.common import RequestSchema, ResponseSchema


# Тема слота — вход генерации, а не пост: длинные простыни в неё не пишут.
TOPIC_LIMIT = 2000


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError("Укажите часовой пояс времени публикации")
    return value


class SlotCreateRequest(RequestSchema):
    """Новый слот календаря. ``generate_at`` считает сервер."""

    publish_at: datetime
    rubric_id: int | None = None
    topic: str = Field(default="", max_length=TOPIC_LIMIT)

    _check_publish_at = field_validator("publish_at")(_aware)


class SlotPatchRequest(RequestSchema):
    """Частичная правка слота: время, рубрика, тема."""

    publish_at: datetime | None = None
    rubric_id: int | None = None
    topic: str | None = Field(default=None, max_length=TOPIC_LIMIT)

    _check_publish_at = field_validator("publish_at")(_aware)

    @model_validator(mode="after")
    def at_least_one_change(self) -> "SlotPatchRequest":
        if not self.model_fields_set:
            raise ValueError("Нечего менять: укажите время, рубрику или тему")
        return self


class SlotRubricResponse(ResponseSchema):
    id: int
    name: str | None = None


class SlotPostResponse(ResponseSchema):
    """Данные карточки предпросмотра: отдельный запрос за постом не нужен.

    ``title`` и ``checks_summary`` пустые до треков генерации и проверок.
    """

    id: int
    title: str | None = None
    excerpt: str = ""
    media_thumb_url: str | None = None
    checks_summary: dict[str, Any] | None = None


class SlotResponse(ResponseSchema):
    id: int
    publish_at: datetime
    generate_at: datetime
    rubric: SlotRubricResponse | None = None
    topic: str
    status: str
    post: SlotPostResponse | None = None
