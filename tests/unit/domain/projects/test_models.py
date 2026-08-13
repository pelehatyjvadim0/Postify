from datetime import UTC, datetime

import pytest

from postify.domain.projects.models import (
    CallToAction,
    ChannelConnection,
    ContentFormat,
    ContentProject,
    ProjectConfiguration,
    PublicationRoute,
    SourceConnection,
)


def configuration(**overrides) -> ProjectConfiguration:
    values = {
        "selection_policy_version": "project-1-v1",
        "selection_rules": ("advertising", "out_of_scope"),
        "topic_terms": ("практика",),
        "topic_exclusion_terms": ("лотерея",),
        "advertising_terms": ("реклама",),
        "hiring_terms": (),
        "technical_release_terms": (),
        "practical_terms": (),
        "selection_freshness_days": 30,
        "daily_analysis_limit": 12,
        "daily_package_limit": 3,
        "priority_freshness_days": 14,
        "fresh_share_percent": 90,
        "reserve_share_percent": 10,
        "review_required": True,
        "article_max_bytes": 2_000_000,
        "media_max_bytes": 10_000_000,
        "analysis_timeout_seconds": 600,
    }
    values.update(overrides)
    return ProjectConfiguration(**values)


def test_project_configuration_rejects_quota_shares_not_totalling_100() -> None:
    with pytest.raises(ValueError, match="100"):
        configuration(fresh_share_percent=80, reserve_share_percent=10)


def test_project_configuration_rejects_package_limit_above_analysis_limit() -> None:
    with pytest.raises(ValueError, match="анализа"):
        configuration(daily_analysis_limit=2, daily_package_limit=3)


def test_project_configuration_requires_markers_for_enabled_rule() -> None:
    with pytest.raises(ValueError, match="маркеры"):
        configuration(advertising_terms=())


def test_project_normalises_identity_and_validates_timezone() -> None:
    project = ContentProject(
        id=1,
        name="  Технологии   просто ",
        topic=" Практичные AI-инструменты ",
        language="ru",
        audience="Небольшие продуктовые команды",
        timezone="Europe/Moscow",
        configuration=configuration(),
        created_at=datetime(2026, 8, 12, tzinfo=UTC),
        updated_at=datetime(2026, 8, 12, tzinfo=UTC),
    )

    assert project.name == "Технологии просто"
    assert project.topic == "Практичные AI-инструменты"

    with pytest.raises(ValueError, match="часовой пояс"):
        ContentProject(
            1,
            "Проект",
            "Тема",
            "ru",
            "Аудитория",
            "Mars/Olympus",
            configuration(),
            datetime(2026, 8, 12, tzinfo=UTC),
            datetime(2026, 8, 12, tzinfo=UTC),
        )


def test_connections_and_route_keep_provider_details_out_of_common_fields() -> None:
    source = SourceConnection(
        3,
        1,
        "hn_algolia",
        "Новости разработчиков",
        True,
        {"query": "python", "tags": "story", "hits": 50},
        "0 7 * * 1-5",
    )
    channel = ChannelConnection(
        4,
        1,
        "telegram",
        "Основной канал",
        True,
        {"chat_id": "-100123"},
        True,
        "connected",
    )
    content_format = ContentFormat(
        5,
        1,
        "Практический разбор B",
        "text",
        "Хук, польза, ограничения и следующий шаг.",
        True,
    )
    cta = CallToAction(6, 1, "Открыть источник", "Посмотреть пример", "source", None, True)
    route = PublicationRoute(7, 1, content_format.id, channel.id, cta.id, True)

    assert source.provider == "hn_algolia"
    assert channel.provider == "telegram"
    assert route.format_id == 5
    assert route.channel_id == 4
    assert route.cta_id == 6
    assert "telegram" not in PublicationRoute.__annotations__


@pytest.mark.parametrize("link_mode", ["none", "source", "custom"])
def test_call_to_action_accepts_supported_link_modes(link_mode: str) -> None:
    url = "https://example.com/next" if link_mode == "custom" else None

    assert CallToAction(1, 1, "CTA", "Действие", link_mode, url, True).link_mode == link_mode


def test_custom_call_to_action_requires_absolute_http_url() -> None:
    with pytest.raises(ValueError, match="URL"):
        CallToAction(1, 1, "CTA", "Действие", "custom", "/relative", True)
