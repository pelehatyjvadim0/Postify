from pathlib import Path
from typing import Literal

from pydantic import Field, PostgresDsn, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    database_url: PostgresDsn
    database_readiness_timeout_seconds: float = Field(default=30.0, gt=0)
    run_once_wait_timeout_seconds: float = Field(default=30.0, gt=0)
    postify_on_calendar: str = Field(default="*/5 * * * *", min_length=1)
    postify_timezone: str = Field(default="Europe/Moscow", min_length=1)
    project_topic: str = Field(default="Новости", min_length=1)
    project_language: str = Field(default="ru", min_length=1)
    project_audience: str = Field(default="Широкая аудитория", min_length=1)
    content_batch_size: int = Field(default=100, gt=0)
    content_media_dir: Path = Field(default_factory=lambda: Path.cwd() / "var" / "media")
    content_media_max_bytes: int = Field(default=10_000_000, gt=0)
    content_analysis_timeout_seconds: int = Field(default=60, gt=0)
    content_analyzer: Literal["gemini", "codex"] = "codex"
    content_model: str = Field(default="gpt-5.6-terra", min_length=1)
    content_analysis_reasoning_effort: Literal[
        "low", "medium", "high", "xhigh", "max"
    ] = "high"
    content_source_language: str = Field(default="ar", min_length=1)
    content_tone: str = Field(default="Нейтральный", min_length=1)
    gemini_api_key: SecretStr | None = None
    telegram_api_id: int | None = Field(default=None, gt=0)
    telegram_api_hash: SecretStr | None = None
    postify_secret_key: SecretStr | None = None

    @field_validator("telegram_api_id", mode="before")
    @classmethod
    def empty_telegram_api_id(cls, value):
        return None if value == "" else value

    @model_validator(mode="after")
    def validate_paths(self) -> "Settings":
        if not self.content_media_dir.is_absolute():
            raise ValueError("Каталог медиа должен быть абсолютным")
        return self

class TelegramSettings(BaseSettings):
    """Настройки, нужные только команде доставки."""

    model_config = SettingsConfigDict(extra="ignore")

    telegram_bot_token: SecretStr
    telegram_chat_id: str = Field(min_length=1)
    telegram_timeout_seconds: float = Field(gt=0)
    @field_validator("telegram_chat_id")
    @classmethod
    def validate_nonblank_telegram_value(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Настройка Telegram не может быть пустой")
        return value
