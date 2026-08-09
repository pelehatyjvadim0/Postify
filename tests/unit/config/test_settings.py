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
    "CONTENT_DAILY_ANALYSIS_LIMIT": "12",
    "CONTENT_DAILY_PACKAGE_LIMIT": "3",
    "CONTENT_PRIORITY_FRESHNESS_DAYS": "14",
    "CONTENT_FRESH_SHARE_PERCENT": "90",
    "CONTENT_RESERVE_SHARE_PERCENT": "10",
    "CONTENT_REVIEW_REQUIRED": "true",
    "CONTENT_MEDIA_DIR": "/var/lib/postify/media",
    "CONTENT_ARTICLE_MAX_BYTES": "2000000",
    "CONTENT_MEDIA_MAX_BYTES": "10000000",
    "CONTENT_CODEX_TIMEOUT_SECONDS": "600",
    "TELEGRAM_BOT_TOKEN": "123456:test-token",
    "TELEGRAM_CHAT_ID": "-100123456789",
    "TELEGRAM_TIMEOUT_SECONDS": "10",
    "TELEGRAM_ON_CALENDAR_MORNING": "*-*-* 09:00:00",
    "TELEGRAM_ON_CALENDAR_DAY": "*-*-* 13:00:00",
    "TELEGRAM_ON_CALENDAR_EVENING": "*-*-* 18:00:00",
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

CONTENT_REQUIRED_NAMES = [
    "CONTENT_DAILY_ANALYSIS_LIMIT",
    "CONTENT_DAILY_PACKAGE_LIMIT",
    "CONTENT_PRIORITY_FRESHNESS_DAYS",
    "CONTENT_FRESH_SHARE_PERCENT",
    "CONTENT_RESERVE_SHARE_PERCENT",
    "CONTENT_REVIEW_REQUIRED",
    "CONTENT_MEDIA_DIR",
    "CONTENT_ARTICLE_MAX_BYTES",
    "CONTENT_MEDIA_MAX_BYTES",
    "CONTENT_CODEX_TIMEOUT_SECONDS",
]

TELEGRAM_REQUIRED_NAMES = [
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "TELEGRAM_TIMEOUT_SECONDS",
    "TELEGRAM_ON_CALENDAR_MORNING",
    "TELEGRAM_ON_CALENDAR_DAY",
    "TELEGRAM_ON_CALENDAR_EVENING",
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
                "CONTENT_DAILY_ANALYSIS_LIMIT=12",
                "CONTENT_DAILY_PACKAGE_LIMIT=3",
                "CONTENT_PRIORITY_FRESHNESS_DAYS=14",
                "CONTENT_FRESH_SHARE_PERCENT=90",
                "CONTENT_RESERVE_SHARE_PERCENT=10",
                "CONTENT_REVIEW_REQUIRED=true",
                "CONTENT_MEDIA_DIR=/var/lib/postify/media",
                "CONTENT_ARTICLE_MAX_BYTES=2000000",
                "CONTENT_MEDIA_MAX_BYTES=10000000",
                "CONTENT_CODEX_TIMEOUT_SECONDS=600",
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


def test_settings_exposes_complete_content_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    # Поломка: content-action получает default/хардкод вместо профиля фермы.
    set_required_environment(monkeypatch)

    settings = Settings()

    assert settings.content_daily_analysis_limit == 12
    assert settings.content_daily_package_limit == 3
    assert settings.content_priority_freshness_days == 14
    assert settings.content_fresh_share_percent == 90
    assert settings.content_reserve_share_percent == 10
    assert settings.content_review_required is True
    assert settings.content_media_dir == Path("/var/lib/postify/media")
    assert settings.content_article_max_bytes == 2_000_000
    assert settings.content_media_max_bytes == 10_000_000
    assert settings.content_codex_timeout_seconds == 600


@pytest.mark.parametrize("missing_name", CONTENT_REQUIRED_NAMES)
def test_settings_requires_each_content_value(
    monkeypatch: pytest.MonkeyPatch, missing_name: str
) -> None:
    # Поломка: пропуск настройки незаметно включает чужой профиль.
    set_required_environment(monkeypatch)
    monkeypatch.delenv(missing_name)

    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("CONTENT_DAILY_ANALYSIS_LIMIT", "0"),
        ("CONTENT_DAILY_PACKAGE_LIMIT", "0"),
        ("CONTENT_PRIORITY_FRESHNESS_DAYS", "0"),
        ("CONTENT_ARTICLE_MAX_BYTES", "0"),
        ("CONTENT_MEDIA_MAX_BYTES", "0"),
        ("CONTENT_CODEX_TIMEOUT_SECONDS", "0"),
        ("CONTENT_FRESH_SHARE_PERCENT", "-1"),
        ("CONTENT_RESERVE_SHARE_PERCENT", "101"),
    ],
)
def test_settings_rejects_invalid_content_scalar(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    # Поломка: нулевой/внедиапазонный лимит проходит к application-слою.
    set_required_environment(monkeypatch, **{name: value})

    with pytest.raises(ValidationError):
        Settings()


def test_settings_rejects_package_limit_above_analysis_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Поломка: пакетов можно зарезервировать больше, чем начато анализов.
    set_required_environment(
        monkeypatch,
        CONTENT_DAILY_ANALYSIS_LIMIT="2",
        CONTENT_DAILY_PACKAGE_LIMIT="3",
    )

    with pytest.raises(ValidationError):
        Settings()


def test_settings_requires_content_shares_to_sum_to_one_hundred(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Поломка: credits дрейфуют, если доли не образуют 100%.
    set_required_environment(
        monkeypatch,
        CONTENT_FRESH_SHARE_PERCENT="80",
        CONTENT_RESERVE_SHARE_PERCENT="10",
    )

    with pytest.raises(ValidationError):
        Settings()


def test_settings_requires_absolute_content_media_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    # Поломка: относительный media root пишет файлы в зависящее от cwd место.
    set_required_environment(monkeypatch, CONTENT_MEDIA_DIR="var/lib/postify/media")

    with pytest.raises(ValidationError):
        Settings()


def test_settings_exposes_all_six_telegram_values_without_plain_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Поломка: delivery получает hardcode/default или token как обычную строку.
    from pydantic import SecretStr

    set_required_environment(monkeypatch)
    settings = Settings()

    assert isinstance(settings.telegram_bot_token, SecretStr)
    assert settings.telegram_bot_token.get_secret_value() == "123456:test-token"
    assert settings.telegram_chat_id == "-100123456789"
    assert settings.telegram_timeout_seconds == 10
    assert settings.telegram_on_calendar_morning == "*-*-* 09:00:00"
    assert settings.telegram_on_calendar_day == "*-*-* 13:00:00"
    assert settings.telegram_on_calendar_evening == "*-*-* 18:00:00"
    assert "test-token" not in repr(settings)


@pytest.mark.parametrize("missing_name", TELEGRAM_REQUIRED_NAMES)
def test_settings_requires_each_telegram_value(
    monkeypatch: pytest.MonkeyPatch, missing_name: str
) -> None:
    # Поломка: неполная Telegram-конфигурация доходит до БД/сети.
    set_required_environment(monkeypatch)
    monkeypatch.delenv(missing_name)

    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize("timeout", ["0", "-1"])
def test_settings_requires_positive_telegram_timeout(
    monkeypatch: pytest.MonkeyPatch, timeout: str
) -> None:
    # Поломка: нулевой/отрицательный timeout проходит к HTTP client.
    set_required_environment(monkeypatch, TELEGRAM_TIMEOUT_SECONDS=timeout)

    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize(
    "calendar_name",
    [
        "TELEGRAM_ON_CALENDAR_MORNING",
        "TELEGRAM_ON_CALENDAR_DAY",
        "TELEGRAM_ON_CALENDAR_EVENING",
    ],
)
def test_settings_rejects_blank_telegram_calendar(
    monkeypatch: pytest.MonkeyPatch, calendar_name: str
) -> None:
    # Поломка: whitespace-only слот выглядит настроенным.
    set_required_environment(monkeypatch, **{calendar_name: "   "})

    with pytest.raises(ValidationError):
        Settings()
