from pathlib import Path

import pytest
from pydantic import ValidationError

from postify.config import Settings


def test_settings_reads_current_project_and_content_profile() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://postify:password@localhost:5432/postify",
        project_topic="Практичная автоматизация",
        project_language="ru",
        project_audience="Редакторы",
        content_batch_size=12,
        content_media_dir=Path("/var/lib/postify/media"),
        content_media_max_bytes=10_000_000,
        content_analysis_timeout_seconds=600,
        content_analyzer="codex",
        content_model="gpt-5.6-terra",
        content_analysis_reasoning_effort="medium",
    )

    assert settings.project_topic == "Практичная автоматизация"
    assert settings.content_batch_size == 12
    assert settings.content_analyzer == "codex"
    assert settings.content_model == "gpt-5.6-terra"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("content_batch_size", 0),
        ("content_media_max_bytes", 0),
        ("content_analysis_timeout_seconds", 0),
    ],
)
def test_settings_rejects_nonpositive_technical_limits(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(
            database_url="postgresql+psycopg://postify:password@localhost:5432/postify",
            **{field: value},
        )
