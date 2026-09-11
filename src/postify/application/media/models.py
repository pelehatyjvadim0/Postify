"""Читаемое представление изображения пула.

Поля повторяют раздел 10 контракта плюс ``caption_model``: UI обязан честно
показывать, что подпись сделала заглушка, а не настоящая vision-модель.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class MediaAsset:
    id: int
    project_id: int
    file_path: str
    thumb_path: str | None
    mime: str
    bytes: int
    width: int
    height: int
    content_hash: str
    caption: str | None
    # "mock" означает подпись заглушки; после появления ключа её перевыпускают.
    caption_model: str | None
    caption_status: str
    has_embedding: bool
    uploaded_at: datetime
    last_used_at: datetime | None
    use_count: int
    enabled: bool
    # Прошёл ли актив политику повторов и готов ли к подбору.
    available: bool


@dataclass(frozen=True, slots=True)
class MediaCandidate:
    """Строка шортлиста: изображение и его расстояние до запроса."""

    asset: MediaAsset
    distance: float


@dataclass(frozen=True, slots=True)
class MediaPage:
    items: tuple[MediaAsset, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class MediaCounts:
    """Сводка для карточки проекта: ``media: {total, available}``."""

    total: int
    available: int
