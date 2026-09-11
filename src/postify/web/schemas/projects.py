"""Схемы проекта, его канала и рубрик — разделы 4 и 5 контракта API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from postify.web.schemas.common import RequestSchema, ResponseSchema


class ProjectCreateRequest(RequestSchema):
    """Форма создания спрашивает только название и часовой пояс."""

    name: str = Field(min_length=1, max_length=200)
    timezone: str = Field(min_length=1, max_length=100)


class ProjectUpdateRequest(RequestSchema):
    """Частичная правка: в действие уходят только переданные поля."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    timezone: str | None = Field(default=None, min_length=1, max_length=100)
    language: str | None = Field(default=None, min_length=1, max_length=100)
    audience: str | None = Field(default=None, min_length=1, max_length=500)
    tone: str | None = Field(default=None, min_length=1, max_length=500)
    project_prompt: str | None = Field(default=None, max_length=20_000)
    generation_lead_minutes: int | None = Field(default=None, gt=0, le=43_200)
    publication_mode: Literal["review", "auto"] | None = None
    media_reuse_days: int | None = Field(default=None, gt=0, le=3650)


class ChannelRequest(RequestSchema):
    """Токен бота принимается и больше никогда не возвращается."""

    bot_token: str | None = Field(default=None, min_length=1, max_length=500)
    chat_id: str = Field(min_length=1, max_length=200)


class ChannelResponse(ResponseSchema):
    configured: bool
    chat_id: str
    status: str
    checked_at: datetime | None = None


class ProjectMediaResponse(ResponseSchema):
    """Счётчики пула изображений; наполнит их трек медиа."""

    total: int = 0
    available: int = 0


class ProjectResponse(ResponseSchema):
    id: int
    name: str
    timezone: str
    language: str
    audience: str
    tone: str
    project_prompt: str
    publication_mode: str
    generation_lead_minutes: int
    media_reuse_days: int
    channel: ChannelResponse
    media: ProjectMediaResponse


class ProjectSummaryResponse(ResponseSchema):
    """Строка переключателя проектов в боковой панели."""

    id: int
    name: str
    channel_title: str | None
    publication_mode: str
    counts: dict[str, int]


class RubricCreateRequest(RequestSchema):
    name: str = Field(min_length=1, max_length=200)
    instructions: str = Field(min_length=1, max_length=10_000)
    enabled: bool = True


class RubricUpdateRequest(RequestSchema):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    instructions: str | None = Field(default=None, min_length=1, max_length=10_000)
    enabled: bool | None = None


class RubricResponse(ResponseSchema):
    id: int
    name: str
    instructions: str
    enabled: bool
