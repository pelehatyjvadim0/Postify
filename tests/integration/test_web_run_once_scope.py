from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from postify.bootstrap import open_run_once
from postify.domain.content.models import ExecutionPurpose
from postify.infrastructure.database.engine import create_engine_from_settings
from postify.web.services import WebApplication
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
                    VALUES (2,'Project 2','AI','ru','Teams','Europe/Moscow',
                    CAST(:configuration AS jsonb),:now,:now)"""
                ),
                {"now": datetime(2026, 8, 12, 9, tzinfo=UTC),
                 "configuration": '{"media_max_bytes":10000000,"analysis_timeout_seconds":60,"analysis_batch_size":100}'},
            )
            session.execute(text("""INSERT INTO content_formats
                (project_id,name,kind,instructions,enabled,created_at,updated_at)
                VALUES (2,'Пост','text','Короткий пост',true,:now,:now)"""),
                {"now": datetime(2026, 8, 12, 9, tzinfo=UTC)})
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


def test_web_retry_accepts_project_owned_scheduled_attempt_via_shared_action(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = configured_settings(migrated_database_url)
    engine = create_engine_from_settings(settings)
    api = WebApplication(settings, None)
    captured: list[tuple[int, str, object]] = []
    try:
        with sessionmaker(engine).begin() as session:
            candidate_id = session.execute(
                text(
                    """INSERT INTO candidates
                    (project_id,source_name,source_id,title,url,discovered_at,raw_payload)
                    VALUES (1,'source','scheduled-owner','Scheduled owner',
                            'https://example.test/scheduled-owner',:now,'{}') RETURNING id"""
                ),
                {"now": datetime(2026, 8, 17, 9, tzinfo=UTC)},
            ).scalar_one()
            attempt_id = session.execute(
                text(
                    """INSERT INTO content_attempts
                    (project_id,candidate_id,attempt_no,status,source_url,retry_at,
                     started_at,finished_at)
                    VALUES (1,:candidate,1,'retry_scheduled',
                            'https://example.test/scheduled-owner',:retry_at,:now,:now)
                    RETURNING id"""
                ),
                {
                    "candidate": candidate_id,
                    "now": datetime(2026, 8, 17, 9, tzinfo=UTC),
                    "retry_at": datetime(2026, 8, 18, 9, tzinfo=UTC),
                },
            ).scalar_one()

        def submit(project_id: int, kind: str, **kwargs: object) -> int:
            captured.append((project_id, kind, kwargs["context"]))
            return 88

        monkeypatch.setattr(api, "_submit_operation", submit)

        assert api.retry_analysis(1, attempt_id) == {
            "status": "accepted",
            "operationRunId": 88,
        }
        context = captured[0][2]
        assert context.purpose is ExecutionPurpose.RETRY_ANALYSIS
        assert context.target_attempt_id == attempt_id
    finally:
        api.close()
        engine.dispose()
