from __future__ import annotations

from types import SimpleNamespace
from zoneinfo import ZoneInfo


def test_open_operational_status_passes_fixed_plan_and_configured_boundaries(
    monkeypatch,
) -> None:
    # Поломка: target=3, content limits или POSTIFY_TIMEZONE меняются в bootstrap wiring.
    from postify import bootstrap
    from postify.application.observability import show_status
    from postify.infrastructure.repositories import sqlalchemy_observability

    received: dict[str, object] = {}

    class Engine:
        def dispose(self) -> None:
            received["disposed"] = True

    class Repository:
        def __init__(self, factory) -> None:
            received["factory"] = factory

    class Action:
        def __init__(self, repository, **kwargs) -> None:
            received["repository"] = repository
            received.update(kwargs)

    settings = SimpleNamespace(
        postify_timezone="Europe/Moscow",
        content_daily_analysis_limit=5,
        content_daily_package_limit=3,
    )
    factory = object()
    monkeypatch.setattr(bootstrap, "create_engine_from_settings", lambda _: Engine())
    monkeypatch.setattr(bootstrap, "sessionmaker", lambda _: factory)
    monkeypatch.setattr(sqlalchemy_observability, "SqlAlchemyOperationalStatusRepository", Repository)
    monkeypatch.setattr(show_status, "ShowOperationalStatus", Action)

    with bootstrap.open_operational_status(settings) as action:
        assert isinstance(action, Action)

    assert received["daily_target"] == 3
    assert received["analysis_limit"] == 5
    assert received["package_limit"] == 3
    assert received["timezone"] == ZoneInfo("Europe/Moscow")
    assert received["disposed"] is True
