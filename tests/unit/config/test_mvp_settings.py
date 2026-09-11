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
