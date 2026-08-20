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
    PUBLISHED = "published"


class ExecutionMode(StrEnum):
    AUTOMATIC = "automatic"
    MANUAL = "manual"


class ExecutionActor(StrEnum):
    SCHEDULER = "scheduler"
    UI = "ui"


class ExecutionPurpose(StrEnum):
    RUN_ONCE = "run_once"
    PUBLISH_ONCE = "publish_once"
    MANUAL_SEARCH = "manual_search"
    LOAD_MORE = "load_more"
    RETRY_ANALYSIS = "retry_analysis"
    RETURN_TO_ANALYSIS = "return_to_analysis"
    REGENERATE_POST = "regenerate_post"
    REPLACE_MEDIA = "replace_media"
    PUBLISH_NOW = "publish_now"
    RETRY_DELIVERY = "retry_delivery"


def validate_transition(current: str, target: str) -> None:
    allowed = {
        ("not_started", "processing"),
        ("processing", "awaiting_review"),
        ("processing", "approved"),
        ("awaiting_review", "approved"),
        ("awaiting_review", "rejected"),
        ("approved", "published"),
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
        if type(self.attempt_no) is not int or self.attempt_no < 1:
            raise ContentValidationError("Номер попытки должен быть положительным")


@dataclass(frozen=True, slots=True)
class ContentLimits:
    analysis_limit: int
    package_limit: int
    freshness_days: int
    fresh_share: int
    reserve_share: int


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """Server-owned policy for a pipeline invocation."""
    mode: ExecutionMode | str = ExecutionMode.AUTOMATIC
    actor: ExecutionActor | str = ExecutionActor.SCHEDULER
    purpose: ExecutionPurpose | str | None = None
    batch_size: int | None = None
    target_attempt_id: int | None = None
    target_package_id: int | None = None
    target_delivery_id: int | None = None

    def __post_init__(self) -> None:
        try:
            mode = ExecutionMode(self.mode)
            actor = ExecutionActor(self.actor)
        except ValueError as error:
            raise ContentValidationError("Некорректный execution context") from error
        purpose = self.purpose
        if purpose is None:
            if mode is ExecutionMode.AUTOMATIC:
                purpose = ExecutionPurpose.RUN_ONCE
            elif self.target_attempt_id is not None:
                purpose = ExecutionPurpose.RETRY_ANALYSIS
            elif self.target_package_id is not None:
                purpose = ExecutionPurpose.RETURN_TO_ANALYSIS
            elif self.batch_size == 3:
                purpose = ExecutionPurpose.LOAD_MORE
            else:
                purpose = ExecutionPurpose.MANUAL_SEARCH
        try:
            purpose = ExecutionPurpose(purpose)
        except ValueError as error:
            raise ContentValidationError("Некорректная ручная операция") from error
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "actor", actor)
        object.__setattr__(self, "purpose", purpose)
        if (mode, actor) not in {
            (ExecutionMode.AUTOMATIC, ExecutionActor.SCHEDULER),
            (ExecutionMode.MANUAL, ExecutionActor.UI),
        }:
            raise ContentValidationError("Некорректный execution context")
        if self.batch_size is not None and (type(self.batch_size) is not int or self.batch_size < 1):
            raise ContentValidationError("Некорректный размер партии")
        for value, message in (
            (self.target_attempt_id, "Некорректная попытка анализа"),
            (self.target_package_id, "Некорректный пакет"),
            (self.target_delivery_id, "Некорректная доставка"),
        ):
            if value is not None and (type(value) is not int or value < 1):
                raise ContentValidationError(message)
        targets = tuple(
            value
            for value in (
                self.target_attempt_id,
                self.target_package_id,
                self.target_delivery_id,
            )
            if value is not None
        )
        if len(targets) > 1:
            raise ContentValidationError("Допустима только одна цель ручной операции")
        if mode is ExecutionMode.AUTOMATIC:
            if purpose not in {
                ExecutionPurpose.RUN_ONCE,
                ExecutionPurpose.PUBLISH_ONCE,
            } or self.batch_size is not None or targets:
                raise ContentValidationError("Автоматический запуск не принимает ручную цель")
            return
        expected = {
            ExecutionPurpose.LOAD_MORE: (3, None, None, None),
            ExecutionPurpose.RETRY_ANALYSIS: (1, self.target_attempt_id, None, None),
            ExecutionPurpose.RETURN_TO_ANALYSIS: (1, None, self.target_package_id, None),
            ExecutionPurpose.REGENERATE_POST: (1, None, self.target_package_id, None),
            ExecutionPurpose.REPLACE_MEDIA: (None, None, self.target_package_id, None),
            ExecutionPurpose.PUBLISH_NOW: (None, None, self.target_package_id, None),
            ExecutionPurpose.RETRY_DELIVERY: (None, None, None, self.target_delivery_id),
        }.get(purpose)
        if expected is not None and (
            self.batch_size,
            self.target_attempt_id,
            self.target_package_id,
            self.target_delivery_id,
        ) != expected:
            raise ContentValidationError("Некорректная цель ручной операции")
        if expected is None and targets:
            raise ContentValidationError("Операция не принимает цель")

    @property
    def is_manual(self) -> bool:
        return self.mode is ExecutionMode.MANUAL


AUTOMATIC_CONTEXT = ExecutionContext()
MANUAL_UI_CONTEXT = ExecutionContext(
    mode=ExecutionMode.MANUAL,
    actor=ExecutionActor.UI,
    purpose=ExecutionPurpose.LOAD_MORE,
    batch_size=3,
)


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
    source_url_allowed: bool = False
    history: list[object] = field(default_factory=list)

    def __post_init__(self):
        if not self.source_url_allowed and self.source_url in self.post_text:
            raise ContentValidationError("URL источника нельзя добавлять в пост")
