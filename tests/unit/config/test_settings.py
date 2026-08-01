from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from postify.config import Settings


REQUIRED_ENVIRONMENT = {
    "DATABASE_URL": "postgresql+psycopg://postify:password@localhost:5432/postify",
    "HN_ALGOLIA_URL": "https://example.test/api/v1/search_by_date",
    "HN_QUERY": "python",
    "HN_TAGS": "story,ask_hn",
    "HN_HITS_PER_PAGE": "42",
    "POSTGRESQL_SYSTEMD_UNIT": "postgresql-custom.service",
    "POSTGRESQL_OWNERSHIP": "shared_allowed",
    "POSTIFY_ON_CALENDAR": "0 9 * * 1-5",
    "POSTIFY_TIMEZONE": "Europe/Moscow",
}


def set_required_environment(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> None:
    for name, value in {**REQUIRED_ENVIRONMENT, **overrides}.items():
        monkeypatch.setenv(name, value)


def test_settings_reads_all_values_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    set_required_environment(monkeypatch)

    settings = Settings()

    assert str(settings.database_url) == REQUIRED_ENVIRONMENT["DATABASE_URL"]
    assert settings.hn_algolia_url == REQUIRED_ENVIRONMENT["HN_ALGOLIA_URL"]
    assert settings.hn_query == REQUIRED_ENVIRONMENT["HN_QUERY"]
    assert settings.hn_tags == REQUIRED_ENVIRONMENT["HN_TAGS"]
    assert settings.hn_hits_per_page == 42
    assert settings.database_readiness_timeout_seconds == 30.0
    assert settings.run_once_wait_timeout_seconds == 30.0
    assert settings.postgresql_systemd_unit == REQUIRED_ENVIRONMENT["POSTGRESQL_SYSTEMD_UNIT"]
    assert settings.postgresql_ownership == REQUIRED_ENVIRONMENT["POSTGRESQL_OWNERSHIP"]
    assert settings.postify_on_calendar == REQUIRED_ENVIRONMENT["POSTIFY_ON_CALENDAR"]
    assert settings.postify_timezone == REQUIRED_ENVIRONMENT["POSTIFY_TIMEZONE"]


def test_environment_has_priority_over_passed_env_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    environment_file = tmp_path / ".env"
    environment_file.write_text(
        "\n".join(
            [
                "DATABASE_URL=postgresql+psycopg://file:file@localhost:5432/file",
                "HN_QUERY=from-file",
                "POSTGRESQL_OWNERSHIP=dedicated",
                "POSTIFY_ON_CALENDAR=0 8 * * *",
                "POSTIFY_TIMEZONE=UTC",
            ]
        )
    )
    monkeypatch.setenv("DATABASE_URL", REQUIRED_ENVIRONMENT["DATABASE_URL"])

    settings = Settings(_env_file=environment_file)

    assert str(settings.database_url) == REQUIRED_ENVIRONMENT["DATABASE_URL"]
    assert settings.hn_query == "from-file"
    assert settings.postgresql_ownership == "dedicated"


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("DATABASE_URL", "not-a-dsn"),
        ("POSTGRESQL_SYSTEMD_UNIT", "postgresql"),
        ("HN_HITS_PER_PAGE", "0"),
        ("DATABASE_READINESS_TIMEOUT_SECONDS", "0"),
        ("RUN_ONCE_WAIT_TIMEOUT_SECONDS", "0"),
        ("POSTGRESQL_OWNERSHIP", "other"),
    ],
)
def test_settings_rejects_invalid_configuration(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    set_required_environment(monkeypatch, **{name: value})

    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize(
    "missing_name",
    [
        "DATABASE_URL",
        "HN_QUERY",
        "POSTGRESQL_OWNERSHIP",
        "POSTIFY_ON_CALENDAR",
        "POSTIFY_TIMEZONE",
    ],
)
def test_settings_requires_mandatory_values(
    monkeypatch: pytest.MonkeyPatch, missing_name: str
) -> None:
    set_required_environment(monkeypatch)
    monkeypatch.delenv(missing_name)

    with pytest.raises(ValidationError):
        Settings()
