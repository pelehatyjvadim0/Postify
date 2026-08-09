from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace

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


def test_open_publish_once_records_safe_publish_outcome_without_replacing_result(
    monkeypatch,
) -> None:
    # Поломка: composition root обходит running→succeeded journal или меняет PublishContentResult.
    from postify import bootstrap
    from postify.application.delivery import publish_content
    from postify.application.observability.record_operation import RecordedAction
    from postify.domain.delivery.models import PublishContentResult
    from postify.infrastructure.repositories import sqlalchemy_observability

    events: list[tuple[object, ...]] = []
    expected = PublishContentResult("empty")

    class Engine:
        def dispose(self) -> None:
            events.append(("engine:close",))

    class Underlying:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def execute(self) -> PublishContentResult:
            events.append(("action",))
            return expected

    class Journal:
        def __init__(self, factory) -> None:
            events.append(("journal", factory))

        def start(self, operation, *, now: datetime) -> int:
            events.append(("start", operation.value))
            return 17

        def succeed(self, run_id: int, *, outcome: str, now: datetime) -> None:
            events.append(("succeed", run_id, outcome))

        def fail(self, run_id: int, *, failure_code: str, now: datetime) -> None:
            events.append(("fail", run_id, failure_code))

    factory = object()
    monkeypatch.setattr(bootstrap, "create_engine_from_settings", lambda _: Engine())
    monkeypatch.setattr(bootstrap, "sessionmaker", lambda _: factory)
    monkeypatch.setattr(bootstrap.httpx, "Client", lambda **_: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(publish_content, "PublishContent", Underlying)
    monkeypatch.setattr(sqlalchemy_observability, "SqlAlchemyOperationRunRepository", Journal)

    with bootstrap.open_publish_once(_settings(), _telegram()) as action:
        assert isinstance(action, RecordedAction)
        result = action.execute()

    assert result is expected
    assert ("start", "publish_once") in events
    assert ("action",) in events
    assert ("succeed", 17, "empty") in events
    assert all(event != ("fail", 17, "publish_once_failed") for event in events)
