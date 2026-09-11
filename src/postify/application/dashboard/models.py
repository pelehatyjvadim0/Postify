from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Mapping


@dataclass(frozen=True, slots=True)
class PostHistoryEntry:
    """Одна смена статуса поста: UI показывает её лентой в карточке."""

    status: str
    reason: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PostSummary:
    """Строка списка постов. Текст урезан: список не грузит полные посты."""

    post_id: int
    status: str
    excerpt: str
    char_count: int
    media_available: bool
    created_at: datetime
    updated_at: datetime
    scheduled_at: datetime | None = None
    delivery_status: str | None = None

    @property
    def id(self) -> int:
        """Контракт отдаёт поле ``id``; внутри читаем однозначное ``post_id``."""

        return self.post_id


@dataclass(frozen=True, slots=True)
class PostDetail:
    """Карточка поста: полный текст, снимок генерации, история и доставка."""

    post_id: int
    status: str
    post_text: str
    char_count: int
    media_available: bool
    media_mime: str | None
    generation: Mapping[str, object]
    history: tuple[PostHistoryEntry, ...]
    created_at: datetime
    updated_at: datetime
    scheduled_at: datetime | None = None
    # Доставка одна на пост, поэтому её исход лежит прямо в карточке.
    delivery_status: str | None = None
    delivery_message_id: int | None = None
    failure_code: str | None = None
    failure_reason: str | None = None
    published_at: datetime | None = None

    @property
    def id(self) -> int:
        """См. ``PostSummary.id``."""

        return self.post_id


@dataclass(frozen=True, slots=True)
class PublicationAttempt:
    attempt_no: int
    outcome: str
    code: str | None
    reason: str | None
    message_id: int | None
    started_at: datetime
    finished_at: datetime


@dataclass(frozen=True, slots=True)
class Publication:
    delivery_id: int
    post_id: int
    provider: str | None
    status: str
    attempt_count: int
    attempts: tuple[PublicationAttempt, ...]
    message_id: int | None
    failure_code: str | None
    failure_reason: str | None
    sending_started_at: datetime
    confirmed_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class Operation:
    """Запись журнала операций; по ней же UI опрашивает длительную операцию."""

    run_id: int
    operation: str
    status: str
    outcome: str | None
    failure_code: str | None
    mode: str
    actor: str
    result: Mapping[str, object]
    started_at: datetime
    finished_at: datetime | None
    duration: timedelta | None
