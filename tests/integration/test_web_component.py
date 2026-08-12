from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
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
        client = TestClient(create_app(WebContainer(api=WebApplication(settings, None))))

        bootstrap = client.get("/api/v1/bootstrap")
        dashboard = client.get("/api/v1/projects/1/dashboard")

        assert bootstrap.status_code == 200
        assert bootstrap.json()["activeProject"]["id"] == 1
        assert dashboard.status_code == 200
        assert dashboard.json()["candidate_total"] == 0
    finally:
        engine.dispose()
