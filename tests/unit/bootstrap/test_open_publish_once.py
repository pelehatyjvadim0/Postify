from __future__ import annotations

from dataclasses import dataclass

import httpx

from postify.config import Settings, TelegramSettings


def _settings() -> Settings:
    return Settings(
        database_url="postgresql+psycopg://postify:password@localhost:5432/postify",
        hn_query="python", postgresql_ownership="dedicated", postify_on_calendar="0 9 * * *",
        postify_timezone="Europe/Moscow", selection_policy_version="v1", selection_language="ru",
        selection_audience="test", selection_rules="advertising", selection_topic_terms="tools",
        selection_topic_exclusion_terms="recipes", selection_advertising_terms="ads",
        selection_hiring_terms="jobs", selection_technical_release_terms="release",
        selection_practical_terms="guide", selection_freshness_days=30,
        content_daily_analysis_limit=1, content_daily_package_limit=1,
        content_priority_freshness_days=1, content_fresh_share_percent=100,
        content_reserve_share_percent=0, content_review_required=True,
        content_media_dir="/var/lib/postify/media", content_article_max_bytes=1,
        content_media_max_bytes=1, content_codex_timeout_seconds=1,
    )


def _telegram() -> TelegramSettings:
    return TelegramSettings(
        telegram_bot_token="123456:test-token", telegram_chat_id="-100123456789",
        telegram_timeout_seconds=10, telegram_on_calendar_morning="*-*-* 09:00:00",
        telegram_on_calendar_day="*-*-* 13:00:00", telegram_on_calendar_evening="*-*-* 18:00:00",
    )


def test_open_publish_once_assembles_real_boundary_and_closes_resources(monkeypatch) -> None:
    # Поломка: composition root не импортирует policy или оставляет HTTP/engine открытыми.
    from postify import bootstrap

    events: list[str] = []

    class Engine:
        def dispose(self) -> None:
            events.append("engine:close")

    class Client(httpx.Client):
        def close(self) -> None:
            events.append("client:close")
            super().close()

    monkeypatch.setattr(bootstrap, "create_engine_from_settings", lambda _: Engine())
    monkeypatch.setattr(bootstrap.httpx, "Client", Client)
    with bootstrap.open_publish_once(_settings(), _telegram()) as action:
        assert action.timeout_seconds == 10
        assert action.publisher.chat_id == "-100123456789"

    assert events == ["client:close", "engine:close"]


def test_open_publish_once_closes_engine_when_client_construction_fails(monkeypatch) -> None:
    # Поломка: client exception теряет уже созданный engine.
    from postify import bootstrap

    events: list[str] = []

    @dataclass
    class Engine:
        def dispose(self) -> None:
            events.append("engine:close")

    monkeypatch.setattr(bootstrap, "create_engine_from_settings", lambda _: Engine())
    monkeypatch.setattr(bootstrap.httpx, "Client", lambda **_: (_ for _ in ()).throw(RuntimeError("client")))

    try:
        with bootstrap.open_publish_once(_settings(), _telegram()):
            pass
    except RuntimeError as error:
        assert str(error) == "client"
    else:
        raise AssertionError("Ожидалась ошибка client")
    assert events == ["engine:close"]
