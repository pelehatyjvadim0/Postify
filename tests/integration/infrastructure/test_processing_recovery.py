from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from postify.application.content.manual_operations import ManualContentOperations
from postify.infrastructure.repositories.sqlalchemy_content_recovery import (
    generation_lock,
    recover_interrupted_content,
)
from postify.infrastructure.repositories.sqlalchemy_content import SqlAlchemyContentRepository
from postify.infrastructure.repositories.sqlalchemy_schedule import SqlAlchemyScheduleRepository
from tests.integration.infrastructure.test_sqlalchemy_delivery import _seed_package


pytestmark = pytest.mark.integration
NOW = datetime(2026, 9, 5, tzinfo=UTC)


def _interrupted_package(engine) -> tuple[int, int, int]:
    package_id = _seed_package(engine, status="processing")
    with engine.begin() as connection:
        attempt_id = connection.execute(
            text("SELECT attempt_id FROM content_packages WHERE id=:package"),
            {"package": package_id},
        ).scalar_one()
        connection.execute(
            text(
                "UPDATE content_attempts SET status='processing', finished_at=NULL "
                "WHERE id=:attempt"
            ),
            {"attempt": attempt_id},
        )
        connection.execute(
            text(
                "UPDATE candidates SET source_text='Полный текст после recovery' "
                "WHERE id=(SELECT candidate_id FROM content_attempts WHERE id=:attempt)"
            ),
            {"attempt": attempt_id},
        )
        run_ids = {}
        for operation in ("run_once", "manual_search"):
            run_ids[operation] = connection.execute(
                text(
                    "INSERT INTO operation_runs(project_id,operation,status,mode,actor,started_at) "
                    "VALUES (1,:operation,'running','automatic','scheduler',:now) RETURNING id"
                ),
                {"operation": operation, "now": NOW},
            ).scalar_one()
        job_id = connection.execute(
            text(
                "INSERT INTO scheduled_jobs(project_id,kind,scheduled_for,operation_run_id,"
                "status,attempt_count,created_at,updated_at) "
                "VALUES (1,'run_once',:now,:run,'queued',0,:now,:now) RETURNING id"
            ),
            {"run": run_ids["run_once"], "now": NOW},
        ).scalar_one()
    return package_id, attempt_id, job_id


def test_startup_recovery_fails_interrupted_content_and_its_running_journal(
    migrated_database_url: str,
) -> None:
    engine = create_engine(migrated_database_url)
    sessions = sessionmaker(engine)
    package_id, attempt_id, job_id = _interrupted_package(engine)
    try:
        assert recover_interrupted_content(sessions, 1, NOW) == 2
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT status,failure_code,finished_at FROM content_attempts WHERE id=:id"),
                {"id": attempt_id},
            ).one() == ("failed", "processing_interrupted", NOW)
            assert connection.execute(
                text("SELECT status FROM content_packages WHERE id=:id"),
                {"id": package_id},
            ).scalar_one() == "failed"
            assert connection.execute(
                text(
                    "SELECT status,reason,created_at FROM content_package_status_history "
                    "WHERE package_id=:id ORDER BY id DESC LIMIT 1"
                ),
                {"id": package_id},
            ).one() == ("failed", "processing_interrupted", NOW)
            assert connection.execute(
                text(
                    "SELECT operation,status,failure_code FROM operation_runs "
                    "WHERE operation IN ('run_once','manual_search') ORDER BY operation"
                )
            ).all() == [
                ("manual_search", "failed", "manual_search_failed"),
                ("run_once", "failed", "run_once_failed"),
            ]
            assert connection.execute(
                text("SELECT status,lease_expires_at FROM scheduled_jobs WHERE id=:id"),
                {"id": job_id},
            ).one() == ("failed", None)
        assert SqlAlchemyScheduleRepository(sessions).claim_pending(now=NOW) == ()
        repository = SqlAlchemyContentRepository(sessions)
        retry = repository.claim(
            now=NOW,
            batch_size=1,
            context=ManualContentOperations(repository).retry_analysis(attempt_id),
        )
        assert [(item.attempt_no, item.source_text) for item in retry] == [
            (2, "Полный текст после recovery")
        ]
    finally:
        engine.dispose()


def test_recovery_does_not_touch_processing_content_while_generation_lock_is_held(
    migrated_database_url: str,
) -> None:
    engine = create_engine(migrated_database_url)
    sessions = sessionmaker(engine)
    package_id, attempt_id, _ = _interrupted_package(engine)
    try:
        with generation_lock(sessions, 1):
            assert recover_interrupted_content(sessions, 1, NOW) == 0
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT status FROM content_attempts WHERE id=:id"),
                {"id": attempt_id},
            ).scalar_one() == "processing"
            assert connection.execute(
                text("SELECT status FROM content_packages WHERE id=:id"),
                {"id": package_id},
            ).scalar_one() == "processing"
    finally:
        engine.dispose()
