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
    "SELECTION_POLICY_VERSION": "developer-tools-v1",
    "SELECTION_LANGUAGE": "ru",
    "SELECTION_AUDIENCE": "Разработчики прикладных инструментов",
    "SELECTION_RULES": "advertising,out_of_scope,hiring,technical_without_use",
    "SELECTION_TOPIC_TERMS": "инструменты,postgresql",
    "SELECTION_TOPIC_EXCLUSION_TERMS": "рецепт,кулинария",
    "SELECTION_ADVERTISING_TERMS": "реклама,партнёрский",
    "SELECTION_HIRING_TERMS": "вакансия,нанимаем",
    "SELECTION_TECHNICAL_RELEASE_TERMS": "релиз,версия",
    "SELECTION_PRACTICAL_TERMS": "руководство,пример",
    "SELECTION_FRESHNESS_DAYS": "30",
}


SELECTION_REQUIRED_NAMES = [
    "SELECTION_POLICY_VERSION",
    "SELECTION_LANGUAGE",
    "SELECTION_AUDIENCE",
    "SELECTION_RULES",
    "SELECTION_TOPIC_TERMS",
    "SELECTION_TOPIC_EXCLUSION_TERMS",
    "SELECTION_ADVERTISING_TERMS",
    "SELECTION_HIRING_TERMS",
    "SELECTION_TECHNICAL_RELEASE_TERMS",
    "SELECTION_PRACTICAL_TERMS",
    "SELECTION_FRESHNESS_DAYS",
]


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
                "SELECTION_POLICY_VERSION=file-v1",
                "SELECTION_LANGUAGE=ru",
                "SELECTION_AUDIENCE=Читатели тестового профиля",
                "SELECTION_RULES=advertising,hiring",
                "SELECTION_TOPIC_TERMS=данные",
                "SELECTION_TOPIC_EXCLUSION_TERMS=спорт",
                "SELECTION_ADVERTISING_TERMS=реклама",
                "SELECTION_HIRING_TERMS=вакансия",
                "SELECTION_TECHNICAL_RELEASE_TERMS=релиз",
                "SELECTION_PRACTICAL_TERMS=пример",
                "SELECTION_FRESHNESS_DAYS=14",
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
        *SELECTION_REQUIRED_NAMES,
    ],
)
def test_settings_requires_mandatory_values(
    monkeypatch: pytest.MonkeyPatch, missing_name: str
) -> None:
    set_required_environment(monkeypatch)
    monkeypatch.delenv(missing_name)

    with pytest.raises(ValidationError):
        Settings()


def test_selection_profile_preserves_rule_order_and_normalizes_csv_values() -> None:
    # Поломка: профиль сортирует правила либо сохраняет пробелы/регистр CSV-словарей.
    values = {name.lower(): value for name, value in REQUIRED_ENVIRONMENT.items()}
    values.update(
        selection_rules="  Hiring, advertising  ",
        selection_topic_terms="  PostgreSQL,  Инструменты разработчика ",
    )

    configured = Settings(**values)

    assert configured.selection_rules == ("hiring", "advertising")
    assert configured.selection_topic_terms == ("postgresql", "инструменты разработчика")


@pytest.mark.parametrize(
    "selection_rules",
    ["advertising,unknown", "advertising,ADVERTISING"],
)
def test_selection_profile_rejects_unknown_or_case_insensitive_duplicate_rules(
    selection_rules: str,
) -> None:
    # Поломка: неизвестное или повторное правило молча меняет состав/приоритет политики.
    values = {name.lower(): value for name, value in REQUIRED_ENVIRONMENT.items()}
    values["selection_rules"] = selection_rules

    with pytest.raises(ValidationError):
        Settings(**values)


@pytest.mark.parametrize(
    ("selection_rules", "dictionary_name"),
    [
        ("advertising", "selection_advertising_terms"),
        ("out_of_scope", "selection_topic_exclusion_terms"),
        ("hiring", "selection_hiring_terms"),
        ("technical_without_use", "selection_technical_release_terms"),
        ("technical_without_use", "selection_practical_terms"),
    ],
)
def test_selection_profile_rejects_empty_dictionary_for_enabled_rule(
    selection_rules: str,
    dictionary_name: str,
) -> None:
    # Поломка: включённое правило без маркеров выглядит рабочим, но никогда не срабатывает.
    values = {name.lower(): value for name, value in REQUIRED_ENVIRONMENT.items()}
    values.update(selection_rules=selection_rules, **{dictionary_name: " ,  , "})

    with pytest.raises(ValidationError):
        Settings(**values)


@pytest.mark.parametrize(
    "dictionary_name",
    [
        "selection_topic_terms",
        "selection_topic_exclusion_terms",
        "selection_advertising_terms",
        "selection_hiring_terms",
        "selection_technical_release_terms",
        "selection_practical_terms",
    ],
)
def test_selection_profile_rejects_case_insensitive_duplicate_terms(
    dictionary_name: str,
) -> None:
    # Поломка: один и тот же нормализованный термин хранится в профиле дважды.
    values = {name.lower(): value for name, value in REQUIRED_ENVIRONMENT.items()}
    values[dictionary_name] = "Маркер, маркер"

    with pytest.raises(ValidationError):
        Settings(**values)


@pytest.mark.parametrize("freshness_days", ["0", "-1"])
def test_selection_profile_requires_positive_freshness_days(freshness_days: str) -> None:
    # Поломка: нулевое/отрицательное окно делает сигнал свежести бессмысленным.
    values = {name.lower(): value for name, value in REQUIRED_ENVIRONMENT.items()}
    values["selection_freshness_days"] = freshness_days

    with pytest.raises(ValidationError):
        Settings(**values)
