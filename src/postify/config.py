from pathlib import Path
from typing import Literal

from pydantic import Field, PostgresDsn, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    database_url: PostgresDsn
    database_readiness_timeout_seconds: float = Field(default=30.0, gt=0)
    postify_timezone: str = Field(default="Europe/Moscow", min_length=1)
    content_media_dir: Path = Field(default_factory=lambda: Path.cwd() / "var" / "media")
    content_media_max_bytes: int = Field(default=10_000_000, gt=0)
    content_analysis_timeout_seconds: int = Field(default=60, gt=0)
    content_analyzer: Literal["codex", "openrouter"] = "codex"
    content_model: str = Field(default="gpt-5.6-terra", min_length=1)
    content_reasoning_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    openrouter_api_key: SecretStr | None = None
    # Одна модель на текст и vision: OpenRouter отдаёт и то и другое одним
    # эндпоинтом, так что разделять настройку незачем.
    openrouter_model: str = Field(default="google/gemini-3.1-flash-lite", min_length=1)
    # Отдельная настройка: эмбеддинги у OpenRouter — свой эндпоинт и свои модели.
    openrouter_embedding_model: str = Field(
        default="openai/text-embedding-3-small", min_length=1
    )
    # Провайдер vision и эмбеддингов. ``auto`` — OpenRouter при заданном
    # OPENROUTER_API_KEY, иначе заглушка; так мок отключается появлением ключа,
    # а не правкой кода. ``mock`` и ``openrouter`` — принудительный выбор.
    ai_media_provider: Literal["auto", "mock", "openrouter"] = "auto"
    postify_secret_key: SecretStr | None = None
    # Общего бота опрашивает FakeTG; отдельного — само приложение.
    auth_bot_token: SecretStr | None = None
    auth_bot_username: str | None = None
    auth_bot_relay_url: str | None = None
    # Пустая строка означает открытый вход: любой подтвердивший себя в боте
    # заводит аккаунт. Непустой список сужает вход до перечисленных id.
    auth_allowed_telegram_ids: str = ""

    @property
    def allowed_telegram_ids(self) -> frozenset[str]:
        """Разобранный список разрешённых telegram_user_id; пустой — вход открыт."""
        return frozenset(
            part.strip()
            for part in self.auth_allowed_telegram_ids.split(",")
            if part.strip()
        )

    @model_validator(mode="after")
    def validate_paths(self) -> "Settings":
        if not self.content_media_dir.is_absolute():
            raise ValueError("Каталог медиа должен быть абсолютным")
        return self
