from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, PostgresDsn, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.sources import NoDecode


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    database_url: PostgresDsn
    hn_algolia_url: str = "https://hn.algolia.com/api/v1/search_by_date"
    hn_query: str = Field(min_length=1)
    hn_tags: str = "story"
    hn_hits_per_page: int = Field(default=100, ge=1)
    database_readiness_timeout_seconds: float = Field(default=30.0, gt=0)
    run_once_wait_timeout_seconds: float = Field(default=30.0, gt=0)
    postgresql_systemd_unit: str = "postgresql.service"
    postgresql_ownership: Literal["dedicated", "shared_allowed"]
    postify_on_calendar: str = Field(min_length=1)
    postify_timezone: str = Field(min_length=1)
    selection_policy_version: str = Field(min_length=1)
    selection_language: str = Field(min_length=1)
    selection_audience: str = Field(min_length=1)
    selection_rules: Annotated[tuple[str, ...], NoDecode]
    selection_topic_terms: Annotated[tuple[str, ...], NoDecode]
    selection_topic_exclusion_terms: Annotated[tuple[str, ...], NoDecode]
    selection_advertising_terms: Annotated[tuple[str, ...], NoDecode]
    selection_hiring_terms: Annotated[tuple[str, ...], NoDecode]
    selection_technical_release_terms: Annotated[tuple[str, ...], NoDecode]
    selection_practical_terms: Annotated[tuple[str, ...], NoDecode]
    selection_freshness_days: int = Field(gt=0)
    content_daily_analysis_limit: int = Field(gt=0)
    content_daily_package_limit: int = Field(gt=0)
    content_priority_freshness_days: int = Field(gt=0)
    content_fresh_share_percent: int = Field(ge=0, le=100)
    content_reserve_share_percent: int = Field(ge=0, le=100)
    content_review_required: bool
    content_media_dir: Path
    content_article_max_bytes: int = Field(gt=0)
    content_media_max_bytes: int = Field(gt=0)
    content_codex_timeout_seconds: int = Field(gt=0)
    telegram_bot_token: SecretStr
    telegram_chat_id: str = Field(min_length=1)
    telegram_timeout_seconds: float = Field(gt=0)
    telegram_on_calendar_morning: str = Field(min_length=1)
    telegram_on_calendar_day: str = Field(min_length=1)
    telegram_on_calendar_evening: str = Field(min_length=1)

    @field_validator(
        "selection_rules",
        "selection_topic_terms",
        "selection_topic_exclusion_terms",
        "selection_advertising_terms",
        "selection_hiring_terms",
        "selection_technical_release_terms",
        "selection_practical_terms",
        mode="before",
    )
    @classmethod
    def normalise_csv(cls, value: object) -> tuple[str, ...]:
        items = value.split(",") if isinstance(value, str) else value
        if not isinstance(items, (tuple, list)):
            raise ValueError("Ожидается CSV")
        normalised = tuple(" ".join(str(item).casefold().split()) for item in items)
        normalised = tuple(item for item in normalised if item)
        if len(set(normalised)) != len(normalised):
            raise ValueError("Повторяющиеся значения недопустимы")
        return normalised

    @model_validator(mode="after")
    def validate_selection_profile(self) -> "Settings":
        allowed = {"advertising", "out_of_scope", "hiring", "technical_without_use"}
        if not self.selection_rules or any(
            rule not in allowed for rule in self.selection_rules
        ):
            raise ValueError("Неизвестное или пустое правило отбора")
        required = {
            "advertising": (self.selection_advertising_terms,),
            "out_of_scope": (self.selection_topic_exclusion_terms,),
            "hiring": (self.selection_hiring_terms,),
            "technical_without_use": (
                self.selection_technical_release_terms,
                self.selection_practical_terms,
            ),
        }
        if any(not terms for rule in self.selection_rules for terms in required[rule]):
            raise ValueError("Включённому правилу нужны маркеры")
        if self.content_daily_package_limit > self.content_daily_analysis_limit:
            raise ValueError("Лимит пакетов не может превышать лимит анализа")
        if self.content_fresh_share_percent + self.content_reserve_share_percent != 100:
            raise ValueError("Доли контентной очереди должны составлять 100%")
        if not self.content_media_dir.is_absolute():
            raise ValueError("Каталог медиа должен быть абсолютным")
        return self

    @field_validator("postgresql_systemd_unit")
    @classmethod
    def validate_postgresql_systemd_unit(cls, value: str) -> str:
        if not value.endswith(".service"):
            raise ValueError("Имя systemd-unit должно оканчиваться на .service")
        return value

    @field_validator("telegram_chat_id", "telegram_on_calendar_morning", "telegram_on_calendar_day", "telegram_on_calendar_evening")
    @classmethod
    def validate_nonblank_telegram_value(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Настройка Telegram не может быть пустой")
        return value
