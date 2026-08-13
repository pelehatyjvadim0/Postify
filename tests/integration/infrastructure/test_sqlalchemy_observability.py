from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from threading import Event, get_ident
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker


pytestmark = pytest.mark.integration
NOW = datetime(2026, 8, 9, 9, tzinfo=UTC)
DAY = date(2026, 8, 9)
DAY_START = datetime(2026, 8, 8, 21, tzinfo=UTC)
DAY_END = datetime(2026, 8, 9, 21, tzinfo=UTC)


def _api():
    # Отсутствующий Wave 5 API не ломает collection остального suite.
    from postify.domain.observability.models import OperationKind
    from postify.infrastructure.repositories.sqlalchemy_observability import (
        SqlAlchemyOperationalStatusRepository,
        SqlAlchemyOperationRunRepository,
    )

    return OperationKind, SqlAlchemyOperationalStatusRepository, SqlAlchemyOperationRunRepository


def _repositories(engine):
    _, StatusRepository, RunRepository = _api()
    factory = sessionmaker(engine)
    return StatusRepository(factory), RunRepository(factory)


def _seed_candidate(connection, marker: str, *, decision: str | None = None) -> int:
    candidate_id = connection.execute(
        text(
            "INSERT INTO candidates "
            "(project_id, source_name, source_id, title, url, discovered_at, raw_payload) "
            "VALUES (1, 'hn', :marker, :marker, :url, :now, '{}'::jsonb) RETURNING id"
        ),
        {"marker": marker, "url": f"https://source.test/{marker}", "now": NOW},
    ).scalar_one()
    if decision is not None:
        connection.execute(
            text(
                "INSERT INTO candidate_decisions "
                "(project_id,candidate_id,status,reason,explanation,signals,policy_version,decided_at) "
                "VALUES (1,:id,:status,:reason,'safe','{}'::jsonb,'v1',:now)"
            ),
            {
                "id": candidate_id,
                "status": decision,
                "reason": "eligible_for_ai" if decision == "selected" else "advertising",
                "now": NOW,
            },
        )
    return candidate_id


def _seed_package(
    connection,
    marker: str,
    *,
    package_status: str = "approved",
    attempt_status: str = "packaged",
    created_at: datetime = NOW,
) -> int:
    candidate_id = _seed_candidate(connection, marker, decision="selected")
    attempt_id = connection.execute(
        text(
            "INSERT INTO content_attempts "
            "(project_id,candidate_id,attempt_no,tier,status,source_url,article_title,article_text,"
            "analysis,started_at,finished_at) "
            "VALUES (1,:candidate_id,1,'fresh',:status,:url,'title','article','analysis',"
            ":now,:now) RETURNING id"
        ),
        {
            "candidate_id": candidate_id,
            "status": attempt_status,
            "url": f"https://source.test/{marker}",
            "now": created_at,
        },
    ).scalar_one()
    return connection.execute(
        text(
            "INSERT INTO content_packages "
            "(project_id,attempt_id,source_url,context,analysis,post_text,media_path,media_mime,"
            "media_source_type,media_source_url,review_required,status,created_at,updated_at) "
            "VALUES (1,:attempt_id,:url,'context','analysis',:post_text,:path,'image/png',"
            "'og',:media_url,true,:status,:now,:now) RETURNING id"
        ),
        {
            "attempt_id": attempt_id,
            "url": f"https://source.test/{marker}",
            "post_text": f"SENTINEL-POST-{marker}",
            "path": f"/media/SENTINEL-{marker}.png",
            "media_url": f"https://private.invalid/{marker}.png",
            "status": package_status,
            "now": created_at,
        },
    ).scalar_one()


def _seed_delivery(
    connection,
    package_id: int,
    *,
    status: str,
    attempt_no: int = 1,
    confirmed_at: datetime | None = None,
    media_deleted_at: datetime | None = None,
) -> int:
    return connection.execute(
        text(
            "INSERT INTO telegram_deliveries "
            "(project_id,package_id,status,attempt_no,message_id,sending_started_at,confirmed_at,"
            "media_deleted_at,failure_code,failure_reason,created_at,updated_at) "
            "VALUES (1,:package_id,:status,:attempt_no,:message_id,:now,:confirmed_at,"
            ":media_deleted_at,:failure_code,:failure_reason,:now,:now) RETURNING id"
        ),
        {
            "package_id": package_id,
            "status": status,
            "attempt_no": attempt_no,
            "message_id": 700 + package_id if status == "published" else None,
            "now": NOW,
            "confirmed_at": confirmed_at,
            "media_deleted_at": media_deleted_at,
            "failure_code": f"safe_{status}" if status in {"retryable", "failed", "uncertain"} else None,
            "failure_reason": "SENTINEL-PRIVATE-REASON" if status in {"retryable", "failed", "uncertain"} else None,
        },
    ).scalar_one()


def _table_counts(connection) -> dict[str, int]:
    tables = (
        "candidates",
        "candidate_decisions",
        "content_daily_usage",
        "content_attempts",
        "content_packages",
        "content_package_status_history",
        "telegram_deliveries",
        "telegram_delivery_attempts",
        "operation_runs",
    )
    return {
        table: connection.execute(text(f'SELECT count(*) FROM "{table}"')).scalar_one()
        for table in tables
    }


def test_operation_run_start_and_success_are_independently_committed(
    migrated_database_url: str,
) -> None:
    # Поломка: running не commit до action или terminal fields пишутся несогласованно.
    OperationKind, *_ = _api()
    engine = create_engine(migrated_database_url)
    _, repository = _repositories(engine)
    try:
        run_id = repository.start(OperationKind.RUN_ONCE, now=NOW)
        with engine.connect() as connection:
            assert connection.execute(
                text(
                    "SELECT operation,status,outcome,failure_code,started_at,finished_at "
                    "FROM operation_runs WHERE id=:id"
                ),
                {"id": run_id},
            ).one() == ("run_once", "running", None, None, NOW, None)

        repository.succeed(run_id, outcome="completed", now=NOW + timedelta(seconds=2))
        with engine.connect() as connection:
            assert connection.execute(
                text(
                    "SELECT status,outcome,failure_code,finished_at FROM operation_runs WHERE id=:id"
                ),
                {"id": run_id},
            ).one() == ("succeeded", "completed", None, NOW + timedelta(seconds=2))
    finally:
        engine.dispose()


def test_two_process_repositories_exclude_same_running_project_operation(
    migrated_database_url: str,
) -> None:
    # Поломка review: process-local active set не защищает от второго UI process.
    OperationKind, *_ = _api()
    first_engine = create_engine(migrated_database_url)
    second_engine = create_engine(migrated_database_url)
    _, first = _repositories(first_engine)
    _, second = _repositories(second_engine)
    try:
        first_run = first.start(OperationKind.RUN_ONCE, now=NOW)

        with pytest.raises(RuntimeError, match="operation_busy"):
            second.start(OperationKind.RUN_ONCE, now=NOW + timedelta(seconds=1))

        publish_run = second.start(
            OperationKind.PUBLISH_ONCE, now=NOW + timedelta(seconds=1)
        )
        first.fail(
            first_run,
            failure_code="run_once_failed",
            now=NOW + timedelta(seconds=2),
        )
        second.fail(
            publish_run,
            failure_code="publish_once_failed",
            now=NOW + timedelta(seconds=2),
        )
    finally:
        first_engine.dispose()
        second_engine.dispose()


def test_operation_run_rejects_second_terminal_transition(
    migrated_database_url: str,
) -> None:
    # Поломка: update без `status=running` переписывает завершённый run.
    OperationKind, *_ = _api()
    engine = create_engine(migrated_database_url)
    _, repository = _repositories(engine)
    try:
        run_id = repository.start(OperationKind.PUBLISH_ONCE, now=NOW)
        repository.fail(run_id, failure_code="publish_once_failed", now=NOW + timedelta(seconds=1))

        with pytest.raises(ValueError, match="running"):
            repository.succeed(run_id, outcome="published", now=NOW + timedelta(seconds=2))

        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT status,outcome,failure_code FROM operation_runs WHERE id=:id"),
                {"id": run_id},
            ).one() == ("failed", None, "publish_once_failed")
    finally:
        engine.dispose()


def test_operation_terminal_sql_failure_rolls_back_to_running(
    migrated_database_url: str,
) -> None:
    # Поломка: terminal SQL failure оставляет частичные outcome/time вместо видимого running.
    OperationKind, *_ = _api()
    engine = create_engine(migrated_database_url)
    _, repository = _repositories(engine)
    try:
        run_id = repository.start(OperationKind.PUBLISH_ONCE, now=NOW)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE FUNCTION reject_operation_finish() RETURNS trigger LANGUAGE plpgsql AS $$ "
                    "BEGIN IF NEW.status <> 'running' THEN RAISE EXCEPTION 'forced'; END IF; "
                    "RETURN NEW; END $$"
                )
            )
            connection.execute(
                text(
                    "CREATE TRIGGER reject_operation_finish BEFORE UPDATE ON operation_runs "
                    "FOR EACH ROW EXECUTE FUNCTION reject_operation_finish()"
                )
            )

        with pytest.raises(DBAPIError):
            repository.succeed(run_id, outcome="published", now=NOW + timedelta(seconds=1))

        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT status,outcome,failure_code,finished_at FROM operation_runs WHERE id=:id"),
                {"id": run_id},
            ).one() == ("running", None, None, None)
    finally:
        engine.dispose()


def test_snapshot_uses_exact_ready_predicate_and_local_day_interval(
    migrated_database_url: str,
) -> None:
    # Поломка: failed/uncertain/sending считаются ready или confirmed delivery вне local day попадает в today.
    engine = create_engine(migrated_database_url)
    repository, _ = _repositories(engine)
    try:
        with engine.begin() as connection:
            no_delivery = _seed_package(connection, "ready-new")
            retryable = _seed_package(connection, "ready-retry")
            failed = _seed_package(connection, "blocked-failed")
            uncertain = _seed_package(connection, "blocked-uncertain")
            sending = _seed_package(connection, "blocked-sending")
            _seed_delivery(connection, retryable, status="retryable")
            _seed_delivery(connection, failed, status="failed")
            _seed_delivery(connection, uncertain, status="uncertain")
            _seed_delivery(connection, sending, status="sending")
            for marker, confirmed_at in (
                ("published-before", DAY_START - timedelta(microseconds=1)),
                ("published-start", DAY_START),
                ("published-end", DAY_END - timedelta(microseconds=1)),
                ("published-after", DAY_END),
            ):
                package_id = _seed_package(connection, marker, package_status="published")
                _seed_delivery(
                    connection,
                    package_id,
                    status="published",
                    confirmed_at=confirmed_at,
                    media_deleted_at=confirmed_at,
                )

        snapshot = repository.snapshot(
            day=DAY,
            day_start=DAY_START,
            day_end=DAY_END,
        )

        assert snapshot.delivery_ready_ids == (no_delivery, retryable)
        assert snapshot.published_today == 2
        grouped = {item.code: (item.count, item.ids) for item in snapshot.delivery}
        assert grouped["ready"] == (2, (no_delivery, retryable))
        assert grouped["failed"] == (1, (failed,))
        assert grouped["uncertain"] == (1, (uncertain,))
        assert grouped["sending"] == (1, (sending,))
        assert grouped["published"][0] == 4
    finally:
        engine.dispose()


def test_snapshot_returns_newest_ten_delivery_attempts_with_safe_fields(
    migrated_database_url: str,
) -> None:
    # Поломка: newest limit reversed/нет limit/package ID или история раскрывает reason/post/path/URL.
    engine = create_engine(migrated_database_url)
    repository, _ = _repositories(engine)
    package_ids: list[int] = []
    try:
        with engine.begin() as connection:
            for index in range(12):
                package_id = _seed_package(
                    connection,
                    f"history-{index}",
                    package_status="published",
                    created_at=NOW + timedelta(minutes=index),
                )
                package_ids.append(package_id)
                delivery_id = _seed_delivery(
                    connection,
                    package_id,
                    status="published",
                    confirmed_at=NOW + timedelta(minutes=index),
                    media_deleted_at=NOW + timedelta(minutes=index),
                )
                connection.execute(
                    text(
                        "INSERT INTO telegram_delivery_attempts "
                        "(project_id,delivery_id,attempt_no,outcome,code,reason,started_at,finished_at,message_id) "
                        "VALUES (1,:delivery_id,1,'published',NULL,:reason,:started,:finished,:message_id)"
                    ),
                    {
                        "delivery_id": delivery_id,
                        "reason": f"SENTINEL-PRIVATE-{index}",
                        "started": NOW + timedelta(minutes=index),
                        "finished": NOW + timedelta(minutes=index, seconds=1),
                        "message_id": 900 + index,
                    },
                )

        snapshot = repository.snapshot(
            day=DAY,
            day_start=DAY_START,
            day_end=DAY_END,
            limit=10,
        )

        assert [item.package_id for item in snapshot.latest_delivery_attempts] == list(
            reversed(package_ids[2:])
        )
        assert [item.message_id for item in snapshot.latest_delivery_attempts] == list(
            reversed(range(902, 912))
        )
        rendered = repr(snapshot.latest_delivery_attempts)
        assert "SENTINEL" not in rendered
        assert "private.invalid" not in rendered
        assert "/media/" not in rendered
    finally:
        engine.dispose()


def test_snapshot_is_read_only_for_every_persisted_table(
    migrated_database_url: str,
) -> None:
    # Поломка: status создаёт operation run, claim, retry, cleanup или иное write.
    engine = create_engine(migrated_database_url)
    repository, _ = _repositories(engine)
    try:
        with engine.begin() as connection:
            _seed_package(connection, "read-only")
            before = _table_counts(connection)

        repository.snapshot(day=DAY, day_start=DAY_START, day_end=DAY_END)

        with engine.connect() as connection:
            assert _table_counts(connection) == before
    finally:
        engine.dispose()


def test_snapshot_remains_consistent_when_a_complete_graph_is_committed_mid_read(
    migrated_database_url: str,
) -> None:
    # Поломка: READ COMMITTED смешивает candidate counts до commit и package/history после commit.
    engine = create_engine(migrated_database_url, pool_size=4)
    repository, _ = _repositories(engine)
    first_select_finished = Event()
    writer_finished = Event()
    snapshot_thread: list[int] = []
    paused = False

    @event.listens_for(engine, "after_cursor_execute")
    def pause_after_first_select(connection, cursor, statement, parameters, context, executemany):
        nonlocal paused
        if (
            snapshot_thread
            and get_ident() == snapshot_thread[0]
            and statement.lstrip().upper().startswith("SELECT")
            and not paused
        ):
            paused = True
            first_select_finished.set()
            assert writer_finished.wait(timeout=5)

    def read_snapshot():
        snapshot_thread.append(get_ident())
        return repository.snapshot(day=DAY, day_start=DAY_START, day_end=DAY_END)

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(read_snapshot)
            assert first_select_finished.wait(timeout=5)
            with engine.begin() as connection:
                _seed_package(connection, f"concurrent-{uuid4().hex}")
            writer_finished.set()
            snapshot = future.result(timeout=5)

        # Новый graph либо целиком виден, либо целиком не виден; внутри snapshot нет torn read.
        selected = next((item.count for item in snapshot.candidate_decisions if item.code == "selected"), 0)
        packaged = next((item.count for item in snapshot.content_attempts if item.code == "packaged"), 0)
        approved = next((item.count for item in snapshot.packages if item.code == "approved"), 0)
        assert snapshot.candidate_total == selected == packaged == approved
    finally:
        event.remove(engine, "after_cursor_execute", pause_after_first_select)
        writer_finished.set()
        engine.dispose()


def test_snapshot_counts_only_requested_project(migrated_database_url: str) -> None:
    engine = create_engine(migrated_database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO content_projects "
                "(id,name,topic,language,audience,timezone,configuration,created_at,updated_at) "
                "VALUES (2,'Второй','Тема','ru','Аудитория','UTC','{}'::jsonb,now(),now())"
            )
        )
        for project_id in (1, 2):
            connection.execute(
                text(
                    "INSERT INTO candidates "
                    "(project_id,source_name,source_id,title,url,discovered_at,raw_payload) "
                    "VALUES (:project,'source',:source,'Title','https://example.test',:now,'{}'::jsonb)"
                ),
                {"project": project_id, "source": str(project_id), "now": NOW},
            )
    try:
        _, StatusRepository, _ = _api()
        first = StatusRepository(sessionmaker(engine), project_id=1)
        second = StatusRepository(sessionmaker(engine), project_id=2)

        assert first.snapshot(day=DAY, day_start=DAY_START, day_end=DAY_END).candidate_total == 1
        assert second.snapshot(day=DAY, day_start=DAY_START, day_end=DAY_END).candidate_total == 1
    finally:
        engine.dispose()
