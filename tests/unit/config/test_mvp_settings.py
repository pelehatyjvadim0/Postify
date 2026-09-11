from pathlib import Path

import pytest
from pydantic import ValidationError

from postify.config import Settings


DATABASE_URL = "postgresql+psycopg://postify:password@localhost:5432/postify"


def test_settings_reads_current_content_profile() -> None:
    settings = Settings(
        database_url=DATABASE_URL,
        content_media_dir=Path("/var/lib/postify/media"),
        content_media_max_bytes=10_000_000,
        content_analysis_timeout_seconds=600,
        content_analyzer="codex",
        content_model="gpt-5.6-terra",
        content_reasoning_effort="medium",
    )

    assert settings.content_analyzer == "codex"
    assert settings.content_model == "gpt-5.6-terra"
    assert settings.content_reasoning_effort == "medium"


def test_settings_defaults_to_codex_profile() -> None:
    settings = Settings(
        database_url=DATABASE_URL,
        content_media_dir=Path("/var/lib/postify/media"),
    )

    assert settings.content_analyzer == "codex"
    assert settings.content_model == "gpt-5.6-terra"
    assert settings.content_reasoning_effort == "medium"


def test_settings_defaults_to_openrouter_models_without_key() -> None:
    settings = Settings(
        database_url=DATABASE_URL,
        content_media_dir=Path("/var/lib/postify/media"),
    )

    assert settings.openrouter_api_key is None
    assert settings.ai_media_provider == "auto"
    assert settings.openrouter_model == "google/gemini-3.1-flash-lite"
    assert settings.openrouter_embedding_model == "openai/text-embedding-3-small"


def test_settings_accept_openrouter_as_text_analyzer() -> None:
    settings = Settings(
        database_url=DATABASE_URL,
        content_media_dir=Path("/var/lib/postify/media"),
        content_analyzer="openrouter",
        ai_media_provider="openrouter",
    )

    assert settings.content_analyzer == "openrouter"
    assert settings.ai_media_provider == "openrouter"


@pytest.mark.parametrize("field", ["content_analyzer", "ai_media_provider"])
def test_settings_reject_provider_that_is_gone(field: str) -> None:
    # Гемини больше нет: настройка со старым значением должна падать, а не
    # молча уезжать в значение по умолчанию.
    with pytest.raises(ValidationError):
        Settings(
            database_url=DATABASE_URL,
            content_media_dir=Path("/var/lib/postify/media"),
            **{field: "gemini"},
        )


def test_settings_leaves_login_open_without_allowlist() -> None:
    settings = Settings(
        database_url=DATABASE_URL,
        content_media_dir=Path("/var/lib/postify/media"),
    )

    assert settings.auth_bot_token is None
    assert settings.allowed_telegram_ids == frozenset()


def test_settings_parses_allowed_telegram_ids() -> None:
    settings = Settings(
        database_url=DATABASE_URL,
        content_media_dir=Path("/var/lib/postify/media"),
        auth_allowed_telegram_ids=" 111 ,222, ,333 ",
    )

    assert settings.allowed_telegram_ids == frozenset({"111", "222", "333"})


def test_settings_rejects_relative_media_dir() -> None:
    with pytest.raises(ValidationError):
        Settings(database_url=DATABASE_URL, content_media_dir=Path("var/media"))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("content_media_max_bytes", 0),
        ("content_analysis_timeout_seconds", 0),
        ("database_readiness_timeout_seconds", 0),
    ],
)
def test_settings_rejects_nonpositive_technical_limits(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(
            database_url=DATABASE_URL,
            content_media_dir=Path("/var/lib/postify/media"),
            **{field: value},
        )
