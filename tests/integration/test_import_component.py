from __future__ import annotations

from datetime import UTC, datetime
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from typer.testing import CliRunner

from postify.config import Settings
from postify.infrastructure.database.models import CandidateModel


pytestmark = pytest.mark.integration
runner = CliRunner()


def configured_settings(database_url: str) -> Settings:
    return Settings(
        database_url=database_url,
        hn_algolia_url="https://hn.example.test/api/v1/search_by_date",
        hn_query="python",
        hn_tags="story",
        hn_hits_per_page=1,
        postgresql_systemd_unit="postgresql.service",
        postgresql_ownership="dedicated",
        postify_on_calendar="0 9 * * 1-5",
        postify_timezone="Europe/Moscow",
        selection_policy_version="generic-v1",
        selection_language="ru",
        selection_audience="Тестовая аудитория",
        selection_rules="advertising,out_of_scope,hiring,technical_without_use",
        selection_topic_terms="инструмент",
        selection_topic_exclusion_terms="рецепт",
        selection_advertising_terms="реклама",
        selection_hiring_terms="вакансия",
        selection_technical_release_terms="релиз",
        selection_practical_terms="пример",
        selection_freshness_days=30,
        content_daily_analysis_limit=12,
        content_daily_package_limit=3,
        content_priority_freshness_days=14,
        content_fresh_share_percent=90,
        content_reserve_share_percent=10,
        content_review_required=True,
        content_media_dir="/var/lib/postify/media",
        content_article_max_bytes=2_000_000,
        content_media_max_bytes=10_000_000,
        content_codex_timeout_seconds=600,
    )


def tcp_database_url(database_url: str) -> str:
    parts = urlsplit(database_url)
    query = parse_qs(parts.query)
    if "host" not in query:
        return database_url

    return urlunsplit(
        (
            parts.scheme,
            f"{parts.username}@localhost:{query['port'][0]}",
            parts.path,
            urlencode({"options": query["options"][0]}),
            "",
        )
    )


def full_hn_hit() -> dict[str, object]:
    return {
        "objectID": "123",
        "title": "Практический Python",
        "url": "https://example.test/practical-python",
        "created_at_i": int(datetime(2026, 8, 1, 10, 0, tzinfo=UTC).timestamp()),
        "author": "alice",
    }


def _patch_run_once_lifecycle_resources(monkeypatch, bootstrap, events: list[str]):
    class TrackingClient(httpx.Client):
        def close(self) -> None:
            events.append("client:close")
            super().close()

    class TrackingEngine:
        def dispose(self) -> None:
            events.append("engine:dispose")

    session_factory = object()
    monkeypatch.setattr(bootstrap.httpx, "Client", TrackingClient)
    monkeypatch.setattr(
        bootstrap,
        "create_engine_from_settings",
        lambda settings: TrackingEngine(),
    )
    monkeypatch.setattr(bootstrap, "sessionmaker", lambda engine: session_factory)
    return session_factory


def test_open_importer_persists_one_hn_hit_and_keeps_duplicate_out_of_second_session(
    migrated_database_url: str,
) -> None:
    # Break caught: wiring a fake source/repository or losing duplicate protection across sessions.
    from postify.bootstrap import open_importer

    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"hits": [full_hn_hit()]}))
    settings = configured_settings(tcp_database_url(migrated_database_url))

    with open_importer(settings, transport=transport) as importer:
        assert importer.execute().created == 1
        assert importer.execute().created == 0

    engine = create_engine(migrated_database_url)
    try:
        with sessionmaker(engine)() as second_session:
            stored = second_session.scalars(select(CandidateModel)).all()
        assert [(item.source_id, item.title, item.url) for item in stored] == [
            ("123", "Практический Python", "https://example.test/practical-python")
        ]
    finally:
        engine.dispose()


def test_open_importer_closes_client_and_disposes_engine_on_success_and_source_error(monkeypatch) -> None:
    # Break caught: leaking either HTTP or database resources on normal or failing importer lifecycles.
    from postify import bootstrap
    from postify.application.ports.candidate_source import SourceFetchError

    events: list[str] = []

    class TrackingClient(httpx.Client):
        def close(self) -> None:
            events.append("client:close")
            super().close()

    class TrackingEngine:
        def dispose(self) -> None:
            events.append("engine:dispose")

    monkeypatch.setattr(bootstrap.httpx, "Client", TrackingClient)
    monkeypatch.setattr(bootstrap, "create_engine_from_settings", lambda settings: TrackingEngine())
    monkeypatch.setattr(bootstrap, "sessionmaker", lambda engine: object())

    with bootstrap.open_importer(configured_settings("postgresql+psycopg://unused")):
        pass

    assert events == ["client:close", "engine:dispose"]
    events.clear()

    class FailingSource:
        def __init__(self, **kwargs: object) -> None:
            pass

        def fetch(self) -> list[object]:
            raise SourceFetchError("источник недоступен")

    monkeypatch.setattr(bootstrap, "HnAlgoliaCandidateSource", FailingSource)
    monkeypatch.setattr(bootstrap, "SqlAlchemyCandidateRepository", lambda session_factory: object())

    with pytest.raises(SourceFetchError, match="источник недоступен"):
        with bootstrap.open_importer(configured_settings("postgresql+psycopg://unused")) as importer:
            importer.execute()

    assert events == ["client:close", "engine:dispose"]


def test_open_importer_disposes_engine_when_http_client_construction_fails(monkeypatch) -> None:
    # Break caught: leaking the already-created engine if HTTPX cannot construct its client.
    from postify import bootstrap

    events: list[str] = []

    class TrackingEngine:
        def dispose(self) -> None:
            events.append("engine:dispose")

    def failing_client(**kwargs: object) -> httpx.Client:
        raise RuntimeError("не удалось создать HTTP client")

    monkeypatch.setattr(bootstrap, "create_engine_from_settings", lambda settings: TrackingEngine())
    monkeypatch.setattr(bootstrap.httpx, "Client", failing_client)

    with pytest.raises(RuntimeError, match="не удалось создать HTTP client"):
        with bootstrap.open_importer(configured_settings("postgresql+psycopg://unused")):
            pass

    assert events == ["engine:dispose"]


def test_open_run_once_executes_import_then_selection_and_closes_resources(monkeypatch) -> None:
    # Поломка Important: общий boundary не достигает обоих сценариев либо течёт на success.
    from postify import bootstrap

    events: list[str] = []
    session_factory = _patch_run_once_lifecycle_resources(monkeypatch, bootstrap, events)

    class RecordingSource:
        def __init__(self, **kwargs: object) -> None:
            pass

        def fetch(self) -> list[object]:
            events.append("source:fetch")
            return []

    class CandidateRepository:
        def __init__(self, used_session_factory: object) -> None:
            assert used_session_factory is session_factory

        def save_new(self, candidates: list[object]) -> int:
            events.append("candidates:save")
            return 0

    class DecisionRepository:
        def __init__(self, used_session_factory: object) -> None:
            assert used_session_factory is session_factory

        def find_undecided(self) -> list[object]:
            events.append("decisions:find")
            return []

        def save_new(self, decisions: list[object]) -> set[int]:
            events.append("decisions:save")
            return set()

    monkeypatch.setattr(bootstrap, "HnAlgoliaCandidateSource", RecordingSource)
    monkeypatch.setattr(bootstrap, "SqlAlchemyCandidateRepository", CandidateRepository)
    monkeypatch.setattr(bootstrap, "SqlAlchemyDecisionRepository", DecisionRepository)

    with bootstrap.open_run_once(
        configured_settings("postgresql+psycopg://unused")
    ) as run_once:
        result = run_once.execute()

    assert result.import_result.received == 0
    assert result.import_result.created == 0
    assert result.selection_result.examined == 0
    assert result.selection_result.selected == 0
    assert result.selection_result.rejected == 0
    assert result.selection_result.conflicts == 0
    assert events == [
        "source:fetch",
        "candidates:save",
        "decisions:find",
        "client:close",
        "engine:dispose",
    ]


def test_open_run_once_closes_resources_on_source_execution_error(monkeypatch) -> None:
    # Поломка Important: SourceFetchError из job.execute обходит lifecycle cleanup.
    from postify import bootstrap
    from postify.application.ports.candidate_source import SourceFetchError

    events: list[str] = []
    _patch_run_once_lifecycle_resources(monkeypatch, bootstrap, events)

    class FailingSource:
        def __init__(self, **kwargs: object) -> None:
            pass

        def fetch(self) -> list[object]:
            events.append("source:fetch")
            raise SourceFetchError("источник недоступен")

    monkeypatch.setattr(bootstrap, "HnAlgoliaCandidateSource", FailingSource)
    monkeypatch.setattr(
        bootstrap,
        "SqlAlchemyCandidateRepository",
        lambda used_session_factory: object(),
    )
    monkeypatch.setattr(
        bootstrap,
        "SqlAlchemyDecisionRepository",
        lambda used_session_factory: object(),
    )

    with pytest.raises(SourceFetchError, match="источник недоступен"):
        with bootstrap.open_run_once(
            configured_settings("postgresql+psycopg://unused")
        ) as run_once:
            run_once.execute()

    assert events == ["source:fetch", "client:close", "engine:dispose"]


def test_open_run_once_closes_resources_on_selection_execution_error(monkeypatch) -> None:
    # Поломка Important: ошибка selection после успешного import оставляет ресурсы открытыми.
    from postify import bootstrap

    events: list[str] = []
    session_factory = _patch_run_once_lifecycle_resources(monkeypatch, bootstrap, events)

    class EmptySource:
        def __init__(self, **kwargs: object) -> None:
            pass

        def fetch(self) -> list[object]:
            events.append("source:fetch")
            return []

    class CandidateRepository:
        def __init__(self, used_session_factory: object) -> None:
            assert used_session_factory is session_factory

        def save_new(self, candidates: list[object]) -> int:
            events.append("candidates:save")
            return 0

    class FailingDecisionRepository:
        def __init__(self, used_session_factory: object) -> None:
            assert used_session_factory is session_factory

        def find_undecided(self) -> list[object]:
            events.append("decisions:find")
            raise RuntimeError("решения не загружены")

    monkeypatch.setattr(bootstrap, "HnAlgoliaCandidateSource", EmptySource)
    monkeypatch.setattr(bootstrap, "SqlAlchemyCandidateRepository", CandidateRepository)
    monkeypatch.setattr(
        bootstrap,
        "SqlAlchemyDecisionRepository",
        FailingDecisionRepository,
    )

    with pytest.raises(RuntimeError, match="решения не загружены"):
        with bootstrap.open_run_once(
            configured_settings("postgresql+psycopg://unused")
        ) as run_once:
            run_once.execute()

    assert events == [
        "source:fetch",
        "candidates:save",
        "decisions:find",
        "client:close",
        "engine:dispose",
    ]


def test_open_run_once_disposes_engine_when_http_client_construction_fails(
    monkeypatch,
) -> None:
    # Поломка Important: ошибка HTTP client construction теряет уже созданный engine.
    from postify import bootstrap

    events: list[str] = []

    class TrackingEngine:
        def dispose(self) -> None:
            events.append("engine:dispose")

    def failing_client(**kwargs: object) -> httpx.Client:
        events.append("client:construct")
        raise RuntimeError("не удалось создать HTTP client")

    monkeypatch.setattr(
        bootstrap,
        "create_engine_from_settings",
        lambda settings: TrackingEngine(),
    )
    monkeypatch.setattr(bootstrap.httpx, "Client", failing_client)

    with pytest.raises(RuntimeError, match="не удалось создать HTTP client"):
        with bootstrap.open_run_once(
            configured_settings("postgresql+psycopg://unused")
        ):
            pass

    assert events == ["client:construct", "engine:dispose"]


def test_migrations_at_head_uses_project_configuration_outside_current_directory(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    # Break caught: resolving alembic.ini/scripts from the process CWD rather than the project.
    from postify.bootstrap import migrations_at_head

    monkeypatch.chdir(tmp_path)

    assert migrations_at_head(configured_settings(tcp_database_url(migrated_database_url))) is True


def test_start_reaches_alembic_head_check_from_another_current_directory(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    # Break caught: postify start failing outside the project after PostgreSQL has already started.
    from postify import cli

    events: list[str] = []

    class Systemd:
        def start_postgresql(self) -> None:
            events.append("postgresql:start")

        def enable_and_start_timer(self) -> None:
            events.append("timer:enable-start")

        def enable_and_start_publish_timer(self) -> None:
            events.append("publish-timer:enable-start")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        cli,
        "Settings",
        lambda: configured_settings(tcp_database_url(migrated_database_url)),
    )
    monkeypatch.setattr(cli, "create_systemd_controller", lambda settings: Systemd())
    monkeypatch.setattr(cli, "wait_for_database", lambda settings: events.append("database:ready"))

    result = runner.invoke(cli.app, ["start"])

    assert result.exit_code == 0
    assert result.output == "Таймер Postify запущен\n"
    assert events == ["postgresql:start", "database:ready", "timer:enable-start", "publish-timer:enable-start"]


def test_installed_wheel_checks_migrations_at_head_outside_checkout(
    migrated_database_url: str, tmp_path
) -> None:
    # Break caught: wheel without package-owned Alembic scripts cannot check head from /tmp.
    project_root = Path(__file__).resolve().parents[2]
    wheel_dir = tmp_path / "wheel"
    venv_dir = tmp_path / "venv"
    venv_python = venv_dir / "bin" / "python"

    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(wheel_dir)],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(wheel_dir.glob("postify-*.whl"))
    subprocess.run(
        ["uv", "venv", "--clear", "--python", sys.executable, str(venv_dir)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["uv", "pip", "install", "--python", str(venv_python), str(wheel)],
        check=True,
        capture_output=True,
        text=True,
    )

    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["WHEEL_TEST_DATABASE_URL"] = tcp_database_url(migrated_database_url)
    result = subprocess.run(
        [
            str(venv_python),
            "-c",
            "from postify.bootstrap import migrations_at_head; "
            "from postify.config import Settings; "
            "import os; "
            "settings = Settings(database_url=os.environ['WHEEL_TEST_DATABASE_URL'], "
            "hn_query='test', postgresql_ownership='dedicated', "
            "postify_on_calendar='0 9 * * *', postify_timezone='Europe/Moscow', "
            "selection_policy_version='generic-v1', selection_language='ru', "
            "selection_audience='test', selection_rules='advertising', "
            "selection_topic_terms='tools', selection_topic_exclusion_terms='recipes', "
            "selection_advertising_terms='ads', selection_hiring_terms='jobs', "
            "selection_technical_release_terms='release', selection_practical_terms='guide', "
            "selection_freshness_days=30, content_daily_analysis_limit=12, "
            "content_daily_package_limit=3, content_priority_freshness_days=14, "
            "content_fresh_share_percent=90, content_reserve_share_percent=10, "
            "content_review_required=True, content_media_dir='/var/lib/postify/media', "
            "content_article_max_bytes=2000000, content_media_max_bytes=10000000, "
            "content_codex_timeout_seconds=600); "
            "raise SystemExit(0 if migrations_at_head(settings) else 1)",
        ],
        cwd="/tmp",
        env=environment,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
