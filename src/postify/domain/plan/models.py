"""Доменные модели слота контент-плана.

Слот — единица плана: когда публиковать, в какой рубрике и о чём. Пост
рождается из слота, поэтому пока поста нет, состояние описывает сам слот, а
как только пост появился, статус слота выводится из статуса поста: двух
источников правды у календаря быть не должно.

``generate_at`` считается здесь, а хранится колонкой: планировщик выбирает по
нему «пора генерировать» индексом, а правка запаса времени в настройках
проекта не должна задним числом сдвигать уже стоящие в плане слоты.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum


# Контракт: диапазон календаря не больше 92 дней (квартал плюс сутки).
MAX_PLAN_RANGE_DAYS = 92

# Запас времени на генерацию: сутки по умолчанию, не больше месяца — дальше
# это уже не запас, а другая дата.
MAX_GENERATION_LEAD_MINUTES = 60 * 24 * 31


class PlanValidationError(ValueError):
    """Нарушен инвариант слота контент-плана."""


class InvalidSlotTransition(PlanValidationError):
    """Переход статуса слота не разрешён."""


class SlotTopicRequired(PlanValidationError):
    """Генерация без темы невозможна: вся конкретика поста живёт в теме."""


class PostAlreadyGenerated(PlanValidationError):
    """Тему слота с готовым постом не правят: пост разошёлся бы с планом."""


class SlotTimeTaken(PlanValidationError):
    """На эту минуту в плане проекта уже стоит слот."""


class SlotStatus(StrEnum):
    NO_TOPIC = "no_topic"
    PLANNED = "planned"
    GENERATING = "generating"
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    PUBLISHED = "published"
    FAILED = "failed"
    SKIPPED = "skipped"


# Статусы поста — те же слова, кроме ``rejected``: отклонённый пост возвращает
# слот в план, тема осталась, нужен новый заход генерации.
POST_TO_SLOT_STATUS = {
    "generating": SlotStatus.GENERATING,
    "needs_review": SlotStatus.NEEDS_REVIEW,
    "approved": SlotStatus.APPROVED,
    "published": SlotStatus.PUBLISHED,
    "failed": SlotStatus.FAILED,
    "rejected": SlotStatus.PLANNED,
}

ALLOWED_TRANSITIONS = frozenset(
    {
        (SlotStatus.NO_TOPIC, SlotStatus.PLANNED),
        (SlotStatus.NO_TOPIC, SlotStatus.SKIPPED),
        (SlotStatus.PLANNED, SlotStatus.NO_TOPIC),
        (SlotStatus.PLANNED, SlotStatus.GENERATING),
        (SlotStatus.PLANNED, SlotStatus.SKIPPED),
        (SlotStatus.GENERATING, SlotStatus.NEEDS_REVIEW),
        (SlotStatus.GENERATING, SlotStatus.FAILED),
        (SlotStatus.NEEDS_REVIEW, SlotStatus.APPROVED),
        (SlotStatus.NEEDS_REVIEW, SlotStatus.PLANNED),
        (SlotStatus.APPROVED, SlotStatus.NEEDS_REVIEW),
        (SlotStatus.APPROVED, SlotStatus.PUBLISHED),
        (SlotStatus.APPROVED, SlotStatus.FAILED),
        (SlotStatus.FAILED, SlotStatus.PLANNED),
        (SlotStatus.FAILED, SlotStatus.GENERATING),
        (SlotStatus.FAILED, SlotStatus.SKIPPED),
        (SlotStatus.SKIPPED, SlotStatus.PLANNED),
        (SlotStatus.SKIPPED, SlotStatus.NO_TOPIC),
    }
)

def aware(value: datetime, field: str) -> datetime:
    """Время без таймзоны сравнивать нельзя: план живёт в таймзоне проекта."""
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise PlanValidationError(f"{field} должен содержать часовой пояс")
    return value


def normalise_topic(value: str | None) -> str:
    """Тема — свободный текст; пустая означает слот без темы, а не ошибку."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise PlanValidationError("Тема слота должна быть строкой")
    return value.strip()


def generation_start(publish_at: datetime, lead_minutes: int) -> datetime:
    """``generate_at = publish_at − generation_lead_minutes``."""
    aware(publish_at, "publish_at")
    if type(lead_minutes) is not int or lead_minutes < 0:
        raise PlanValidationError("Запас времени на генерацию должен быть неотрицательным")
    if lead_minutes > MAX_GENERATION_LEAD_MINUTES:
        raise PlanValidationError("Запас времени на генерацию не больше 31 дня")
    return publish_at - timedelta(minutes=lead_minutes)


def status_without_post(topic: str) -> SlotStatus:
    """Слот без темы стоит в календаре как ``no_topic``."""
    return SlotStatus.PLANNED if normalise_topic(topic) else SlotStatus.NO_TOPIC


def slot_status(stored: str, post_status: str | None, *, topic: str) -> SlotStatus:
    """Статус для календаря: пост, если он есть, иначе состояние самого слота."""
    status = SlotStatus(stored)
    if status is SlotStatus.SKIPPED:
        # Пропуск — решение человека, его не перебивает даже готовый пост.
        return status
    if post_status is not None:
        return POST_TO_SLOT_STATUS[post_status]
    if status in {SlotStatus.NO_TOPIC, SlotStatus.PLANNED}:
        return status_without_post(topic)
    return status


def validate_transition(current: str | SlotStatus, target: str | SlotStatus) -> None:
    try:
        pair = (SlotStatus(current), SlotStatus(target))
    except ValueError as error:
        raise InvalidSlotTransition("Неизвестный статус слота") from error
    if pair[0] is pair[1]:
        return
    if pair not in ALLOWED_TRANSITIONS:
        raise InvalidSlotTransition(
            f"Слот в состоянии «{pair[0].value}» нельзя перевести в «{pair[1].value}»"
        )


def validate_range(date_from: date, date_to: date) -> None:
    """Диапазон календаря: по возрастанию и не больше 92 дней (контракт)."""
    if not isinstance(date_from, date) or not isinstance(date_to, date):
        raise PlanValidationError("Границы диапазона должны быть датами")
    if date_to < date_from:
        raise PlanValidationError("Конец диапазона раньше начала")
    if (date_to - date_from).days + 1 > MAX_PLAN_RANGE_DAYS:
        raise PlanValidationError(
            f"Диапазон плана не больше {MAX_PLAN_RANGE_DAYS} дней"
        )


@dataclass(frozen=True, slots=True)
class ContentPlanSlot:
    """Слот плана как он лежит в хранилище."""

    id: int
    project_id: int
    publish_at: datetime
    generate_at: datetime
    rubric_id: int | None
    topic: str
    status: str
    post_id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        for name in ("id", "project_id"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise PlanValidationError(f"{name} должен быть положительным")
        aware(self.publish_at, "publish_at")
        aware(self.generate_at, "generate_at")
        object.__setattr__(self, "topic", normalise_topic(self.topic))
        status = SlotStatus(self.status)
        object.__setattr__(self, "status", status.value)
        if status is SlotStatus.PLANNED and not self.topic:
            raise PlanValidationError("Слот без темы имеет статус no_topic")

    @property
    def has_post(self) -> bool:
        return self.post_id is not None

    def ensure_topic_editable(self) -> None:
        """Тема — вход генерации: у готового поста её правка ломает сверку."""
        if self.has_post:
            raise PostAlreadyGenerated(
                "Пост уже сгенерирован: перегенерируйте или удалите его"
            )

    def ensure_generatable(self) -> None:
        if not self.topic:
            raise SlotTopicRequired("Тема слота не заполнена")
        validate_transition(self.status, SlotStatus.GENERATING)
