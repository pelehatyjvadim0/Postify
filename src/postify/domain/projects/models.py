from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from postify.domain.projects.cron import normalize_cron


class UnsupportedProvider(ValueError):
    """Адаптер подключения не зарегистрирован."""


def _positive(value: int, field: str) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{field} должен быть положительным")


def _normalise_text(value: str, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} должен быть строкой")
    normalised = " ".join(value.split())
    if not normalised:
        raise ValueError(f"{field} не может быть пустым")
    return normalised


def _normalise_terms(values: tuple[str, ...]) -> tuple[str, ...]:
    normalised = tuple(_normalise_text(value, "Маркер").casefold() for value in values)
    if len(set(normalised)) != len(normalised):
        raise ValueError("Маркеры не должны повторяться")
    return normalised


def _aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} должен содержать timezone")


@dataclass(frozen=True, slots=True)
class ProjectConfiguration:
    selection_policy_version: str
    selection_rules: tuple[str, ...]
    topic_terms: tuple[str, ...]
    topic_exclusion_terms: tuple[str, ...]
    advertising_terms: tuple[str, ...]
    hiring_terms: tuple[str, ...]
    technical_release_terms: tuple[str, ...]
    practical_terms: tuple[str, ...]
    selection_freshness_days: int
    daily_analysis_limit: int
    daily_package_limit: int
    priority_freshness_days: int
    fresh_share_percent: int
    reserve_share_percent: int
    review_required: bool
    article_max_bytes: int
    media_max_bytes: int
    analysis_timeout_seconds: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "selection_policy_version",
            _normalise_text(self.selection_policy_version, "Версия политики"),
        )
        allowed = {
            "advertising",
            "out_of_scope",
            "hiring",
            "technical_without_use",
        }
        rules = tuple(self.selection_rules)
        object.__setattr__(self, "selection_rules", rules)
        if not rules or any(
            rule not in allowed for rule in rules
        ):
            raise ValueError("Неизвестное или пустое правило отбора")
        if len(set(rules)) != len(rules):
            raise ValueError("Правила отбора не должны повторяться")
        for name in (
            "topic_terms",
            "topic_exclusion_terms",
            "advertising_terms",
            "hiring_terms",
            "technical_release_terms",
            "practical_terms",
        ):
            object.__setattr__(self, name, _normalise_terms(getattr(self, name)))
        required = {
            "advertising": (self.advertising_terms,),
            "out_of_scope": (self.topic_exclusion_terms,),
            "hiring": (self.hiring_terms,),
            "technical_without_use": (
                self.technical_release_terms,
                self.practical_terms,
            ),
        }
        if any(
            not terms
            for rule in self.selection_rules
            for terms in required[rule]
        ):
            raise ValueError("Для включённого правила нужны маркеры")
        for name in (
            "selection_freshness_days",
            "daily_analysis_limit",
            "daily_package_limit",
            "priority_freshness_days",
            "article_max_bytes",
            "media_max_bytes",
            "analysis_timeout_seconds",
        ):
            _positive(getattr(self, name), name)
        if self.daily_package_limit > self.daily_analysis_limit:
            raise ValueError("Лимит пакетов не может превышать лимит анализа")
        for share in (self.fresh_share_percent, self.reserve_share_percent):
            if type(share) is not int or not 0 <= share <= 100:
                raise ValueError("Доля очереди должна быть от 0 до 100")
        if self.fresh_share_percent + self.reserve_share_percent != 100:
            raise ValueError("Доли очереди должны составлять 100")
        if type(self.review_required) is not bool:
            raise ValueError("review_required должен быть boolean")


@dataclass(frozen=True, slots=True)
class ContentProject:
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
    id: int
    project_id: int
    provider: str
    name: str
    enabled: bool
    configuration: dict[str, Any]
    schedule: str

    def __post_init__(self) -> None:
        _validate_connection(self)
        object.__setattr__(self, "schedule", normalize_cron(self.schedule))


@dataclass(frozen=True, slots=True)
class ChannelConnection:
    id: int
    project_id: int
    provider: str
    name: str
    enabled: bool
    configuration: dict[str, Any]
    secret_configured: bool
    connection_status: str

    def __post_init__(self) -> None:
        _validate_connection(self)
        if type(self.secret_configured) is not bool:
            raise ValueError("secret_configured должен быть boolean")
        object.__setattr__(
            self,
            "connection_status",
            _normalise_text(self.connection_status, "connection_status"),
        )


def _validate_connection(connection: SourceConnection | ChannelConnection) -> None:
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
    id: int
    project_id: int
    name: str
    kind: str
    instructions: str
    enabled: bool

    def __post_init__(self) -> None:
        _positive(self.id, "id")
        _positive(self.project_id, "project_id")
        for field in ("name", "kind", "instructions"):
            object.__setattr__(self, field, _normalise_text(getattr(self, field), field))
        if type(self.enabled) is not bool:
            raise ValueError("enabled должен быть boolean")


@dataclass(frozen=True, slots=True)
class CallToAction:
    id: int
    project_id: int
    name: str
    text: str
    link_mode: str
    custom_url: str | None
    enabled: bool

    def __post_init__(self) -> None:
        _positive(self.id, "id")
        _positive(self.project_id, "project_id")
        object.__setattr__(self, "name", _normalise_text(self.name, "name"))
        object.__setattr__(self, "text", _normalise_text(self.text, "text"))
        if self.link_mode not in {"none", "source", "custom"}:
            raise ValueError("Неизвестный режим ссылки")
        if self.link_mode == "custom":
            parts = urlsplit(self.custom_url or "")
            if parts.scheme not in {"http", "https"} or not parts.netloc:
                raise ValueError("Нужен абсолютный HTTP(S) URL")
        elif self.custom_url is not None:
            raise ValueError("URL допустим только для режима custom")
        if type(self.enabled) is not bool:
            raise ValueError("enabled должен быть boolean")


@dataclass(frozen=True, slots=True)
class PublicationRoute:
    id: int
    project_id: int
    format_id: int
    channel_id: int
    cta_id: int | None
    enabled: bool

    def __post_init__(self) -> None:
        for field in ("id", "project_id", "format_id", "channel_id"):
            _positive(getattr(self, field), field)
        if self.cta_id is not None:
            _positive(self.cta_id, "cta_id")
        if type(self.enabled) is not bool:
            raise ValueError("enabled должен быть boolean")
