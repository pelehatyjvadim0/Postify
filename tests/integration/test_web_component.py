from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from postify.adapters.channels.registry import ChannelProviderRegistry
from postify.adapters.sources.registry import SourceProviderRegistry
from postify.application.projects.bootstrap_project import BootstrapProject
from postify.infrastructure.database.engine import create_engine_from_settings
from postify.infrastructure.repositories.sqlalchemy_projects import SqlAlchemyProjectRepository
from postify.web.app import create_app
from postify.web.dependencies import WebContainer
from postify.web.services import WebApplication
from tests.integration.test_import_component import configured_settings
from tests.unit.web.test_api import ApiClient


pytestmark = pytest.mark.integration


def test_component_bootstrap_and_dashboard_use_real_project_scoped_repositories(
    migrated_database_url: str,
) -> None:
    # Break caught: composition root returns demo data or dashboard skips the project's SQL scope.
    settings = configured_settings(migrated_database_url)
    engine = create_engine_from_settings(settings)
    try:
        projects = SqlAlchemyProjectRepository(sessionmaker(engine))
        BootstrapProject(
            projects,
            SourceProviderRegistry(),
            ChannelProviderRegistry(),
            cipher=None,
            clock=lambda: datetime(2026, 8, 12, 9, tzinfo=UTC),
        ).execute(settings, telegram=None)
        client = ApiClient(create_app(WebContainer(api=WebApplication(settings, None))))

        bootstrap = client.get("/api/v1/bootstrap")
        dashboard = client.get("/api/v1/projects/1/dashboard")

        assert bootstrap.status_code == 200
        assert bootstrap.json()["activeProject"]["id"] == 1
        assert dashboard.status_code == 200
        assert dashboard.json()["candidate_total"] == 0
    finally:
        engine.dispose()


def test_component_serializes_persisted_material_signals(
    migrated_database_url: str,
) -> None:
    # Break caught: immutable decision signals make a populated materials API return 503.
    settings = configured_settings(migrated_database_url)
    engine = create_engine_from_settings(settings)
    try:
        client = ApiClient(create_app(WebContainer(api=WebApplication(settings, None))))
        with engine.begin() as connection:
            candidate_id = connection.execute(
                text(
                    """INSERT INTO candidates
                    (project_id,source_name,source_id,title,url,discovered_at,raw_payload)
                    VALUES (1,'source','component-material','Материал компонента',
                            'https://example.test/material',:now,'{}'::jsonb)
                    RETURNING id"""
                ),
                {"now": datetime(2026, 8, 12, 9, tzinfo=UTC)},
            ).scalar_one()
            connection.execute(
                text(
                    """INSERT INTO candidate_decisions
                    (project_id,candidate_id,status,reason,explanation,signals,
                     policy_version,decided_at)
                    VALUES (1,:candidate,'selected','eligible_for_ai','Полезно',
                            '{"topic":"automation"}'::jsonb,'component-v1',:now)"""
                ),
                {
                    "candidate": candidate_id,
                    "now": datetime(2026, 8, 12, 9, tzinfo=UTC),
                },
            )

        response = client.get("/api/v1/projects/1/materials")

        assert response.status_code == 200
        assert response.json()["items"][0]["decision_signals"] == {
            "topic": "automation"
        }
    finally:
        engine.dispose()


def test_component_lists_persisted_packages_without_status_filter(
    migrated_database_url: str,
) -> None:
    # Break caught: PostgreSQL cannot infer the type of a None status bind and returns 503.
    settings = configured_settings(migrated_database_url)
    engine = create_engine_from_settings(settings)
    try:
        client = ApiClient(create_app(WebContainer(api=WebApplication(settings, None))))
        now = datetime(2026, 8, 12, 9, tzinfo=UTC)
        with engine.begin() as connection:
            candidate_id = connection.execute(
                text(
                    """INSERT INTO candidates
                    (project_id,source_name,source_id,title,url,discovered_at,raw_payload)
                    VALUES (1,'source','component-package','Пакет компонента',
                            'https://example.test/package',:now,'{}'::jsonb)
                    RETURNING id"""
                ),
                {"now": now},
            ).scalar_one()
            attempt_id = connection.execute(
                text(
                    """INSERT INTO content_attempts
                    (project_id,candidate_id,attempt_no,tier,status,source_url,started_at)
                    VALUES (1,:candidate,1,'fresh','packaged',
                            'https://example.test/package',:now) RETURNING id"""
                ),
                {"candidate": candidate_id, "now": now},
            ).scalar_one()
            connection.execute(
                text(
                    """INSERT INTO content_packages
                    (project_id,attempt_id,source_url,context,analysis,post_text,
                     review_required,status,generation_snapshot,created_at,updated_at)
                    VALUES (1,:attempt,'https://example.test/package','Контекст',
                            'Анализ','Текст пакета',true,'awaiting_review',
                            '{}'::jsonb,:now,:now)"""
                ),
                {"attempt": attempt_id, "now": now},
            )

        response = client.get("/api/v1/projects/1/packages")

        assert response.status_code == 200
        assert response.json()["items"][0]["post_text"] == "Текст пакета"
    finally:
        engine.dispose()
