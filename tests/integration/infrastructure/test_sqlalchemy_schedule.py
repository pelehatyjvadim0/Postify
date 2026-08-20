from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from time import monotonic

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from postify.application.scheduling.project_scheduler import ScheduledCommand
from postify.infrastructure.repositories.sqlalchemy_schedule import (
    SqlAlchemyScheduleRepository,
)


pytestmark = pytest.mark.integration
SLOT = datetime(2026, 8, 12, 6, 0, tzinfo=UTC)


def _repository(database_url: str):
    engine = create_engine(database_url)
    return engine, SqlAlchemyScheduleRepository(sessionmaker(engine))


def _seed_project_two(database_url: str) -> None:
    engine = create_engine(database_url)
    now = datetime(2026, 8, 12, tzinfo=UTC)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO content_projects
                    (id,name,topic,language,audience,timezone,configuration,created_at,updated_at)
                VALUES
                    (2,'Project 2','Topic','ru','Audience','UTC','{}',:now,:now)
                """
            ),
            {"now": now},
        )
    engine.dispose()


def _seed_schedule_graph(database_url: str) -> None:
    engine = create_engine(database_url)
    now = datetime(2026, 8, 12, tzinfo=UTC)
    with engine.begin() as connection:
        statements = (
            "UPDATE content_projects SET timezone='Europe/Moscow' WHERE id=1",
            """
                INSERT INTO content_projects
                    (id,name,topic,language,audience,timezone,configuration,created_at,updated_at)
                VALUES
                    (2,'Project 2','Topic','ru','Audience','UTC','{}',:now,:now)
            """,
            """
                INSERT INTO source_connections
                    (id,project_id,provider,name,enabled,configuration,schedule,created_at,updated_at)
                VALUES
                    (101,1,'hn_algolia','Enabled source',true,'{}','0 9 * * *',:now,:now),
                    (102,1,'hn_algolia','Disabled source',false,'{}','0 10 * * *',:now,:now)
            """,
            """
                INSERT INTO content_formats
                    (id,project_id,name,kind,instructions,enabled,created_at,updated_at)
                VALUES
                    (201,1,'Format','post','Text',true,:now,:now),
                    (202,1,'Disabled route format','post','Text',true,:now,:now)
            """,
            """
                INSERT INTO channel_connections
                    (id,project_id,provider,name,enabled,configuration,connection_status,created_at,updated_at)
                VALUES
                    (301,1,'telegram','Channel',true,'{}','ok',:now,:now)
            """,
            """
                INSERT INTO publication_routes
                    (id,project_id,format_id,channel_id,enabled,schedule,created_at,updated_at)
                VALUES
                    (401,1,201,301,true,
                     '{"autopublish": true, "slots": ["09:00", "14:00", "19:00"]}',:now,:now),
                    (402,1,202,301,false,
                     '{"autopublish": true, "slots": ["10:00", "15:00", "20:00"]}',:now,:now)
            """,
        )
        for statement in statements:
            connection.execute(text(statement), {"now": now})
    engine.dispose()


def test_repository_reads_enabled_project_schedules_from_database(
    migrated_database_url: str,
) -> None:
    # Поломка: scheduler использует env/default вместо persisted timezone и enabled resources.
    _seed_schedule_graph(migrated_database_url)
    engine, repository = _repository(migrated_database_url)
    try:
        projects = {item.project_id: item for item in repository.list_schedules()}
    finally:
        engine.dispose()

    assert projects[1].timezone == "Europe/Moscow"
    assert [(item.enabled, item.cron) for item in projects[1].sources] == [
        (True, "0 9 * * *")
    ]
    assert [item.slots for item in projects[1].routes] == [("09:00", "14:00", "19:00")]


def test_two_repository_instances_have_exactly_one_concurrent_claim_winner(
    migrated_database_url: str,
) -> None:
    # Поломка: process-local lock позволяет двум instances создать один slot.
    first_engine, first = _repository(migrated_database_url)
    second_engine, second = _repository(migrated_database_url)
    barrier = Barrier(2)
    command_to_claim = ScheduledCommand(1, "publish_once", SLOT)

    def claim(repository: SqlAlchemyScheduleRepository) -> bool:
        barrier.wait()
        return repository.claim(command_to_claim)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = tuple(pool.map(claim, (first, second)))
    finally:
        first_engine.dispose()
        second_engine.dispose()

    assert sorted(results) == [False, True]


def test_schedule_accept_atomically_creates_operation_or_leaves_slot_retryable(
    migrated_database_url: str,
) -> None:
    # Поломка review: slot claim commit происходит до durable acceptance.
    from postify.domain.observability.models import OperationKind
    from postify.infrastructure.repositories.sqlalchemy_observability import (
        SqlAlchemyOperationRunRepository,
    )

    engine, repository = _repository(migrated_database_url)
    operations = SqlAlchemyOperationRunRepository(sessionmaker(engine), project_id=1)
    busy_slot = SLOT
    retry_slot = SLOT.replace(minute=1)
    try:
        active = operations.start(OperationKind.RUN_ONCE, now=SLOT)
        assert repository.accept(ScheduledCommand(1, "run_once", busy_slot)) is None
        with engine.connect() as connection:
            assert connection.execute(
                text(
                    "SELECT count(*) FROM schedule_slot_claims "
                    "WHERE project_id=1 AND kind='run_once' AND scheduled_for=:slot"
                ),
                {"slot": busy_slot},
            ).scalar_one() == 0

        operations.fail(
            active, failure_code="run_once_failed", now=SLOT.replace(second=1)
        )
        accepted = repository.accept(ScheduledCommand(1, "run_once", retry_slot))
        assert accepted is not None
        assert type(accepted.operation_run_id) is int
        with engine.connect() as connection:
            assert connection.execute(
                text(
                    "SELECT r.status,c.scheduled_for FROM operation_runs r "
                    "JOIN schedule_slot_claims c ON c.project_id=r.project_id "
                    "AND c.kind=r.operation WHERE r.id=:id"
                ),
                {"id": accepted.operation_run_id},
            ).one() == ("running", retry_slot)
    finally:
        engine.dispose()


def test_accepted_job_is_recovered_once_after_repository_restart(
    migrated_database_url: str,
) -> None:
    first_engine, first = _repository(migrated_database_url)
    command = ScheduledCommand(1, "run_once", SLOT.replace(minute=9))
    try:
        accepted = first.accept(command)
        assert accepted is not None
        assert accepted.job_id is not None
    finally:
        first_engine.dispose()

    restarted_engine, restarted = _repository(migrated_database_url)
    try:
        recovered = restarted.claim_pending(now=SLOT)
        assert recovered == (accepted,)
        restarted.acknowledge(accepted.job_id, succeeded=True, now=SLOT)
        assert restarted.claim_pending(now=SLOT + timedelta(hours=1)) == ()
        with restarted_engine.connect() as connection:
            assert connection.execute(
                text(
                    "SELECT status,attempt_count FROM scheduled_jobs WHERE id=:id"
                ),
                {"id": accepted.job_id},
            ).one() == ("succeeded", 1)
    finally:
        restarted_engine.dispose()


def test_claims_are_isolated_by_project(migrated_database_url: str) -> None:
    # Поломка: global advisory/unique key блокирует slot другого project.
    _seed_project_two(migrated_database_url)
    engine, repository = _repository(migrated_database_url)
    try:
        first = repository.claim(ScheduledCommand(1, "run_once", SLOT))
        second = repository.claim(ScheduledCommand(2, "run_once", SLOT))
    finally:
        engine.dispose()

    assert (first, second) == (True, True)


def test_new_repository_after_restart_does_not_reclaim_durable_slot(
    migrated_database_url: str,
) -> None:
    # Поломка: claim хранится в instance memory и пропадает после restart.
    command_to_claim = ScheduledCommand(1, "run_once", SLOT)
    first_engine, first = _repository(migrated_database_url)
    try:
        assert first.claim(command_to_claim) is True
    finally:
        first_engine.dispose()

    restarted_engine, restarted = _repository(migrated_database_url)
    try:
        assert restarted.claim(command_to_claim) is False
    finally:
        restarted_engine.dispose()


def test_advisory_claim_wait_has_database_timeout(
    migrated_database_url: str,
) -> None:
    # Поломка: occupied project advisory lock держит scheduler worker бесконечно.
    locker_engine = create_engine(migrated_database_url)
    repository_engine = create_engine(migrated_database_url)
    locker = locker_engine.connect()
    repository = SqlAlchemyScheduleRepository(
        sessionmaker(repository_engine),
        lock_timeout_ms=100,
        statement_timeout_ms=1_000,
    )
    try:
        locker.execute(text("SELECT pg_advisory_lock(1)"))
        started = monotonic()
        with pytest.raises(DBAPIError):
            repository.claim(ScheduledCommand(1, "run_once", SLOT))
        elapsed = monotonic() - started
    finally:
        locker.execute(text("SELECT pg_advisory_unlock(1)"))
        locker.close()
        locker_engine.dispose()
        repository_engine.dispose()

    assert elapsed < 0.5


def test_schedule_query_wait_has_statement_timeout(
    migrated_database_url: str,
) -> None:
    # Поломка: blocked configuration SELECT держит scheduler worker бесконечно.
    locker_engine = create_engine(migrated_database_url)
    repository_engine = create_engine(migrated_database_url)
    locker = locker_engine.connect()
    repository = SqlAlchemyScheduleRepository(
        sessionmaker(repository_engine),
        lock_timeout_ms=1_000,
        statement_timeout_ms=100,
    )
    try:
        locker.execute(text("LOCK TABLE content_projects IN ACCESS EXCLUSIVE MODE"))
        started = monotonic()
        with pytest.raises(DBAPIError):
            repository.list_schedules()
        elapsed = monotonic() - started
    finally:
        locker.rollback()
        locker.close()
        locker_engine.dispose()
        repository_engine.dispose()

    assert elapsed < 0.5


def test_schedule_claim_migration_downgrades_and_upgrades_again(
    alembic_config,
    isolated_database_url: str,
) -> None:
    # Поломка: migration не удаляет claims при downgrade или не повторяется после rollback.
    command.upgrade(alembic_config, "20260812_07")
    engine = create_engine(isolated_database_url)
    try:
        assert "schedule_slot_claims" in inspect(engine).get_table_names()
    finally:
        engine.dispose()

    command.downgrade(alembic_config, "20260812_06")
    engine = create_engine(isolated_database_url)
    try:
        assert "schedule_slot_claims" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()

    command.upgrade(alembic_config, "20260812_07")
    engine = create_engine(isolated_database_url)
    try:
        assert "schedule_slot_claims" in inspect(engine).get_table_names()
    finally:
        engine.dispose()
