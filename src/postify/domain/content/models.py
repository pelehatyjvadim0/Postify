from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class ContentValidationError(ValueError):
    pass


class InvalidContentTransition(ContentValidationError):
    pass


class PackageStatus(StrEnum):
    NOT_STARTED = "not_started"
    PROCESSING = "processing"
    AWAITING_REVIEW = "awaiting_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"


def validate_transition(current: str, target: str) -> None:
    allowed = {
        ("not_started", "processing"),
        ("processing", "awaiting_review"),
        ("processing", "approved"),
        ("awaiting_review", "approved"),
        ("awaiting_review", "rejected"),
    }
    if (str(current), str(target)) not in allowed:
        raise InvalidContentTransition("Недопустимый переход пакета")


@dataclass(frozen=True, slots=True)
class ExtractedArticle:
    source_url: str
    title: str
    text: str
    image_candidates: tuple[tuple[str, str], ...]

    def __post_init__(self):
        if not self.text.strip():
            raise ContentValidationError("Нужен текст статьи")


@dataclass(frozen=True, slots=True)
class AnalysisInput:
    attempt_id: int
    source_url: str
    title: str
    text: str


@dataclass(frozen=True, slots=True)
class AnalyzedTopic:
    attempt_id: int
    analysis: str
    usefulness: int
    post_text: str | None
    media_query: str | None
    selected: bool = True

    def __post_init__(self):
        if type(self.selected) is not bool:
            raise ContentValidationError("Некорректный выбор темы")
        if not 0 <= self.usefulness <= 100:
            raise ContentValidationError("Некорректная оценка")
        if not self.analysis.strip() or not any(
            "а" <= c.casefold() <= "я" or c in "ёЁ" for c in self.analysis
        ):
            raise ContentValidationError("Нужен русский текст")
        if self.selected and (
            not isinstance(self.post_text, str)
            or not self.post_text.strip()
            or not isinstance(self.media_query, str)
            or not self.media_query.strip()
        ):
            raise ContentValidationError("Нужен запрос медиа")
        if not self.selected and (
            self.post_text is not None or self.media_query is not None
        ):
            raise ContentValidationError("Невыбранная тема не содержит пакет")


@dataclass(frozen=True, slots=True)
class BatchAnalysis:
    topics: tuple[AnalyzedTopic, ...]
    requested_attempt_ids: tuple[int, ...]
    package_limit: int

    def __post_init__(self):
        ids = [t.attempt_id for t in self.topics]
        if (
            len(ids) != len(set(ids))
            or set(ids) != set(self.requested_attempt_ids)
            or len(ids) != len(self.requested_attempt_ids)
            or len(self.selected_topics) > self.package_limit
        ):
            raise ContentValidationError("Некорректный пакет анализа")

    @property
    def selected_topics(self) -> tuple[AnalyzedTopic, ...]:
        return tuple(topic for topic in self.topics if topic.selected)


@dataclass(frozen=True, slots=True)
class ContentAttempt:
    id: int
    candidate_id: int
    attempt_no: int
    tier: str
    status: str
    source_url: str
    started_at: datetime

    def __post_init__(self):
        if self.attempt_no not in (1, 2):
            raise ContentValidationError("Допустимы только две попытки")


@dataclass(frozen=True, slots=True)
class ContentLimits:
    analysis_limit: int
    package_limit: int
    freshness_days: int
    fresh_share: int
    reserve_share: int


@dataclass(frozen=True, slots=True)
class StoredMedia:
    local_path: str
    mime: str
    source_type: str
    source_url: str


@dataclass(slots=True)
class ContentPackage:
    id: int
    attempt_id: int
    source_url: str
    context: str
    analysis: str
    post_text: str
    media_path: str
    media_source_type: str
    media_source_url: str
    review_required: bool
    status: str | PackageStatus
    history: list[object] = field(default_factory=list)

    def __post_init__(self):
        if self.source_url in self.post_text:
            raise ContentValidationError("URL источника нельзя добавлять в пост")
