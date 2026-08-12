from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from postify.bootstrap import open_run_once
from postify.infrastructure.database.engine import create_engine_from_settings
from tests.integration.test_import_component import configured_settings


pytestmark = pytest.mark.integration


def test_real_run_once_records_only_requested_project_scope(
    migrated_database_url: str,
) -> None:
    # Break caught: project 2 UI command constructs default repositories and writes project 1.
    settings = configured_settings(migrated_database_url)
    engine = create_engine_from_settings(settings)
    try:
        with sessionmaker(engine).begin() as session:
            session.execute(
                text(
                    """INSERT INTO content_projects
                    (id,name,topic,language,audience,timezone,configuration,created_at,updated_at)
                    VALUES (2,'Project 2','AI','ru','Teams','Europe/Moscow','{}',:now,:now)"""
                ),
                {"now": datetime(2026, 8, 12, 9, tzinfo=UTC)},
            )
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"hits": []}))

        with open_run_once(settings, project_id=2, transport=transport) as action:
            action.execute()

        with sessionmaker(engine)() as session:
            rows = session.execute(
                text("SELECT project_id FROM operation_runs ORDER BY id")
            ).scalars().all()
        assert rows == [2]
    finally:
        engine.dispose()
