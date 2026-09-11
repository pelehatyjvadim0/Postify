"""Доменные модели контентного проекта.

Проект равен одному Telegram-каналу. Его граф конфигурации — рубрики и
подключение канала. Все сущности неизменяемы после создания и проверяют свои
инварианты в ``__post_init__``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError



REASONING_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})


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
    Технические ограничения одного проекта.

    Конфигурация описывает лимиты подготовки поста и профиль вызова модели.
    Application-слой использует её при сборке конвейера генерации.
    """
    media_max_bytes: int
    analysis_timeout_seconds: int
    analysis_model: str = "gpt-5.6-terra"
    analysis_reasoning_effort: str = "medium"
    tone: str = "Нейтральный"
    # None means approved backlog is sent after restart regardless of its age.
    delivery_lateness_seconds: int | None = None

    def __post_init__(self) -> None:
        """
        Нормализует настройки и проверяет их взаимную согласованность.
        """
        for name in ("media_max_bytes", "analysis_timeout_seconds"):
            _positive(getattr(self, name), name)
        object.__setattr__(
            self,
            "analysis_model",
            _normalise_text(self.analysis_model, "Модель анализа"),
        )
        object.__setattr__(self, "tone", _normalise_text(self.tone, "tone"))
        if self.delivery_lateness_seconds is not None and (
            type(self.delivery_lateness_seconds) is not int
            or self.delivery_lateness_seconds <= 0
        ):
            raise ValueError(
                "Допустимая задержка должна быть положительным целым числом секунд"
            )
        if self.analysis_reasoning_effort not in REASONING_EFFORTS:
            raise ValueError("Неизвестный reasoning effort")


@dataclass(frozen=True, slots=True)
class ContentProject:
    """
    Корневая сущность независимого контентного контура.

    Проект задаёт тему, язык, аудиторию и часовой пояс. Рубрики, слоты плана,
    посты, изображения, канал и операции в хранилище привязываются к его
    ``id``. ``configuration`` определяет, как этот проект генерирует контент.
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
    # Владелец приходит из базы; черновики до вставки его ещё не знают.
    owner_id: int | None = None

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
        if self.owner_id is not None:
            _positive(self.owner_id, "owner_id")


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
    # Время последней проверки канала: контракт отдаёт его как checked_at.
    last_checked_at: datetime | None = None

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


def _validate_connection(connection: ChannelConnection) -> None:
    """
    Проверяет инварианты подключения канала.

    Подключение обязано иметь положительные ID, название провайдера, понятное
    имя, boolean-флаг активности и словарь параметров. Специфическую схему
    ``configuration`` проверяет registry адаптеров.
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
class ProjectRubric:
    """
    Рубрика проекта: требуемая форма и редакционные правила поста.

    ``instructions`` попадают в контекст генерации вместе с промптами проекта.
    Рубрика применяется только если ``enabled=True``.
    """
    id: int
    project_id: int
    name: str
    instructions: str
    enabled: bool

    def __post_init__(self) -> None:
        """Проверяет принадлежность проекту, обязательные тексты и флаг активности."""
        _positive(self.id, "id")
        _positive(self.project_id, "project_id")
        for field in ("name", "instructions"):
            object.__setattr__(self, field, _normalise_text(getattr(self, field), field))
        if type(self.enabled) is not bool:
            raise ValueError("enabled должен быть boolean")
