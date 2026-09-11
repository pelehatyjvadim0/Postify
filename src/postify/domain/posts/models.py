"""Доменные модели поста.

Пост — единица публикации. Его содержимое приходит от агента генерации, а
статус отражает путь от генерации до отправки в канал. Слот контент-плана,
из которого пост рождается, добавляется отдельным треком.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class PostValidationError(ValueError):
    """Нарушен инвариант поста."""


class InvalidPostTransition(PostValidationError):
    """Переход статуса не разрешён."""


class PublicationPlanExpired(InvalidPostTransition):
    """Время публикации прошло, план нужно переназначить."""


class PostStatus(StrEnum):
    GENERATING = "generating"
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"
    PUBLISHED = "published"


ALLOWED_TRANSITIONS = frozenset(
    {
        (PostStatus.GENERATING, PostStatus.NEEDS_REVIEW),
        (PostStatus.GENERATING, PostStatus.FAILED),
        (PostStatus.NEEDS_REVIEW, PostStatus.APPROVED),
        (PostStatus.NEEDS_REVIEW, PostStatus.REJECTED),
        (PostStatus.APPROVED, PostStatus.NEEDS_REVIEW),
        (PostStatus.APPROVED, PostStatus.PUBLISHED),
        (PostStatus.APPROVED, PostStatus.FAILED),
    }
)

TEXT_LIMIT = 4096
TEXT_LIMIT_WITH_MEDIA = 1024


def validate_transition(current: str, target: str) -> None:
    try:
        pair = (PostStatus(current), PostStatus(target))
    except ValueError as error:
        raise InvalidPostTransition("Неизвестный статус поста") from error
    if pair not in ALLOWED_TRANSITIONS:
        raise InvalidPostTransition("Недопустимый переход поста")


def text_length(value: str) -> int:
    """Длина в единицах UTF-16 — так её считает Telegram."""
    return len(value.encode("utf-16-le")) // 2


def validate_text(value: str, *, with_media: bool) -> None:
    limit = TEXT_LIMIT_WITH_MEDIA if with_media else TEXT_LIMIT
    if not value.strip() or text_length(value) > limit:
        raise InvalidPostTransition(
            f"Текст публикации должен содержать от 1 до {limit} символов"
        )


@dataclass(frozen=True, slots=True)
class StoredMedia:
    local_path: str
    mime: str


@dataclass(slots=True)
class Post:
    id: int
    project_id: int
    post_text: str
    media_path: str | None
    media_mime: str | None
    status: str | PostStatus
    created_at: datetime | None = None
    updated_at: datetime | None = None
    scheduled_at: datetime | None = None
    history: list[object] = field(default_factory=list)

    @property
    def char_count(self) -> int:
        return text_length(self.post_text)
