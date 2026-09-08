"""Доменные модели контентного проекта.

Модуль описывает сам проект и его граф конфигурации: источники
материалов, форматы контента, каналы доставки и маршруты
публикации. Все сущности неизменяемы после создания и проверяют свои
инварианты в ``__post_init__``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from postify.domain.projects.cron import normalize_cron


class UnsupportedProvider(ValueError):
    """Адаптер подключения не зарегистрирован."""


def _positive(value: int, field: str) -> None:
    """Проверяет, что идентификатор или лимит — целое положительное число."""
    if type(value) is not int or value <= 0:
        raise ValueError(f"{field} должен быть положительным")


def _normalise_text(value: str, field: str) -> str:
    """Удаляет лишние пробелы и запрещает пустые текстовые поля."""
    if not isinstance(value, str):
        raise ValueError(f"{field} должен быть строкой")
    normalised = " ".join(value.split())
    if not normalised:
        raise ValueError(f"{field} не может быть пустым")
    return normalised


def _aware(value: datetime, field: str) -> None:
    """Гарантирует, что datetime содержит часовой пояс и может безопасно сравниваться."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} должен содержать timezone")


@dataclass(frozen=True, slots=True)
class ProjectConfiguration:
    """
    Хранит все бизнес-правила обработки контента для одного проекта.

    Конфигурация определяет технические ограничения подготовки контента и
    профиль AI. Application-слой использует её для сборки pipeline.
    """
    media_max_bytes: int
    analysis_timeout_seconds: int
    analysis_batch_size: int = 100
    analysis_model: str = "gemini-3.8-flash"
    analysis_reasoning_effort: str = "high"
    source_language: str = "ar"
    tone: str = "Нейтральный"
    # None means approved backlog is sent after restart regardless of its age.
    delivery_lateness_seconds: int | None = None

    def __post_init__(self) -> None:
        """
        Нормализует настройки и проверяет их взаимную согласованность.
        """
        for name in (
            "analysis_batch_size",
            "media_max_bytes",
            "analysis_timeout_seconds",
        ):
            _positive(getattr(self, name), name)
        object.__setattr__(
            self,
            "analysis_model",
            _normalise_text(self.analysis_model, "Модель анализа"),
        )
        for name in ("source_language", "tone"):
            object.__setattr__(self, name, _normalise_text(getattr(self, name), name))
        if self.delivery_lateness_seconds is not None and (type(self.delivery_lateness_seconds) is not int or self.delivery_lateness_seconds <= 0):
            raise ValueError("Допустимая задержка должна быть положительным целым числом секунд")
        allowed_efforts = {"low", "medium", "high", "xhigh", "max"}
        if self.analysis_reasoning_effort not in allowed_efforts:
            raise ValueError("Неизвестный reasoning effort")


@dataclass(frozen=True, slots=True)
class ContentProject:
    """
    Корневая сущность независимого контентного контура.

    Проект задаёт тему, язык, аудиторию и часовой пояс. Все кандидаты,
    источники, пакеты, каналы и операции в хранилище привязываются к его
    ``id``. ``configuration`` определяет, как именно этот проект отбирает и
    генерирует контент.
    """
    id: int
    name: str
    topic: str
    language: str
    audience: str
    timezone: str
    configuration: ProjectConfiguration
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        """
        Проверяет идентичность и базовые атрибуты проекта.

        Пустые название, тема, язык или аудитория недопустимы. Часовой пояс
        должен быть известен ``zoneinfo``, а даты создания и обновления обязаны
        содержать timezone.
        """
        _positive(self.id, "id")
        for field in ("name", "topic", "language", "audience"):
            object.__setattr__(self, field, _normalise_text(getattr(self, field), field))
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            raise ValueError("Неизвестный часовой пояс") from None
        _aware(self.created_at, "created_at")
        _aware(self.updated_at, "updated_at")


@dataclass(frozen=True, slots=True)
class SourceConnection:
    """
    Описывает подключённый к проекту источник материалов.

    ``provider`` выбирает внешний адаптер, ``configuration`` хранит его
    несекретные параметры, ``enabled`` управляет участием в pipeline, а
    ``schedule`` определяет cron-расписание импорта.
    """
    id: int
    project_id: int
    provider: str
    name: str
    enabled: bool
    configuration: dict[str, Any]
    schedule: str

    def __post_init__(self) -> None:
        """Проверяет общие поля подключения и приводит cron к каноническому виду."""
        _validate_connection(self)
        object.__setattr__(self, "schedule", normalize_cron(self.schedule))


@dataclass(frozen=True, slots=True)
class ChannelConnection:
    """
    Описывает внешний канал, в который Postify может доставлять контент.

    Сущность хранит только общедоступную конфигурацию. ``secret_configured``
    сообщает о наличии отдельно зашифрованного секрета, не раскрывая его.
    ``connection_status`` хранит результат последней проверки канала.
    """
    id: int
    project_id: int
    provider: str
    name: str
    enabled: bool
    configuration: dict[str, Any]
    secret_configured: bool
    connection_status: str

    def __post_init__(self) -> None:
        """Проверяет общие поля, флаг секрета и непустой статус подключения."""
        _validate_connection(self)
        if type(self.secret_configured) is not bool:
            raise ValueError("secret_configured должен быть boolean")
        object.__setattr__(
            self,
            "connection_status",
            _normalise_text(self.connection_status, "connection_status"),
        )


def _validate_connection(connection: SourceConnection | ChannelConnection) -> None:
    """
    Проверяет общие инварианты источника и канала.

    Оба типа подключений обязаны иметь положительные ID, название
    провайдера, понятное имя, boolean-флаг активности и словарь
    параметров. Специфическую схему ``configuration`` проверяет registry адаптеров.
    """
    _positive(connection.id, "id")
    _positive(connection.project_id, "project_id")
    object.__setattr__(
        connection, "provider", _normalise_text(connection.provider, "provider")
    )
    object.__setattr__(connection, "name", _normalise_text(connection.name, "name"))
    if type(connection.enabled) is not bool:
        raise ValueError("enabled должен быть boolean")
    if not isinstance(connection.configuration, dict):
        raise ValueError("configuration должна быть объектом")


@dataclass(frozen=True, slots=True)
class ContentFormat:
    """
    Описывает требуемую форму и редакционные правила генерируемого контента.

    ``kind`` обозначает тип формата, а ``instructions`` передаются в AI-анализатор
    как часть generation brief. Формат применяется только если ``enabled=True``.
    """
    id: int
    project_id: int
    name: str
    kind: str
    instructions: str
    enabled: bool

    def __post_init__(self) -> None:
        """Проверяет принадлежность проекту, обязательные тексты и флаг активности."""
        _positive(self.id, "id")
        _positive(self.project_id, "project_id")
        for field in ("name", "kind", "instructions"):
            object.__setattr__(self, field, _normalise_text(getattr(self, field), field))
        if type(self.enabled) is not bool:
            raise ValueError("enabled должен быть boolean")


@dataclass(frozen=True, slots=True)
class PublicationRoute:
    """
    Связывает формат контента и канал доставки.

    Маршрут отвечает на вопрос: «в каком виде и куда публиковать пакет».
    Расписание маршрута хранится в persistence-модели,
    а эта доменная сущность фиксирует сами связи.
    """
    id: int
    project_id: int
    format_id: int
    channel_id: int
    enabled: bool

    def __post_init__(self) -> None:
        """Проверяет все обязательные ссылки маршрута."""
        for field in ("id", "project_id", "format_id", "channel_id"):
            _positive(getattr(self, field), field)
        if type(self.enabled) is not bool:
            raise ValueError("enabled должен быть boolean")
