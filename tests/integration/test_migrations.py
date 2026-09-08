from __future__ import annotations

from alembic import command
from alembic.config import Config
from datetime import UTC, datetime
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError, ProgrammingError


pytestmark = pytest.mark.integration


def test_alembic_requires_dedicated_database_url(monkeypatch) -> None:
    monkeypatch.delenv("POSTIFY_ALEMBIC_DATABASE_URL", raising=False)

    config = Config("alembic.ini")

    try:
        command.upgrade(config, "head")
    except RuntimeError as error:
        assert "POSTIFY_ALEMBIC_DATABASE_URL" in str(error)
    else:
        raise AssertionError("Миграция не должна брать URL из другого источника")


def test_candidates_migration_creates_jsonb_and_named_unique_constraint(
    alembic_config: Config, isolated_database_url: str
) -> None:
    command.upgrade(alembic_config, "base")
    command.upgrade(alembic_config, "20260801_01")

    engine = create_engine(isolated_database_url)
    try:
        inspector = inspect(engine)
        columns = {
            column["name"]: column for column in inspector.get_columns("candidates")
        }
        unique_constraints = inspector.get_unique_constraints("candidates")

        assert columns["raw_payload"]["type"].__class__.__name__ == "JSONB"
        assert {constraint["name"] for constraint in unique_constraints} == {
            "uq_candidates_source_name_source_id"
        }
    finally:
        engine.dispose()

    command.downgrade(alembic_config, "base")

    engine = create_engine(isolated_database_url)
    try:
        assert "candidates" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()

    command.upgrade(alembic_config, "20260801_01")
    engine = create_engine(isolated_database_url)
    try:
        assert "candidates" in inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_candidate_decisions_migration_creates_exact_schema_and_named_constraints(
    alembic_config: Config, isolated_database_url: str
) -> None:
    # Поломка: журнал теряет JSONB, обязательное поле или именованный инвариант.
    command.upgrade(alembic_config, "base")
    command.upgrade(alembic_config, "20260802_02")

    engine = create_engine(isolated_database_url)
    try:
        inspector = inspect(engine)
        columns = {
            column["name"]: column
            for column in inspector.get_columns("candidate_decisions")
        }
        foreign_keys = inspector.get_foreign_keys("candidate_decisions")
        unique_constraints = inspector.get_unique_constraints("candidate_decisions")
        check_constraints = inspector.get_check_constraints("candidate_decisions")

        assert set(columns) == {
            "id",
            "candidate_id",
            "status",
            "reason",
            "explanation",
            "signals",
            "policy_version",
            "decided_at",
        }
        assert columns["id"]["type"].__class__.__name__ == "BIGINT"
        assert columns["candidate_id"]["type"].__class__.__name__ == "BIGINT"
        assert columns["signals"]["type"].__class__.__name__ == "JSONB"
        assert columns["decided_at"]["type"].timezone is True
        assert all(not column["nullable"] for column in columns.values())
        assert [
            (item["name"], item["referred_table"], item["referred_columns"])
            for item in foreign_keys
        ] == [("fk_candidate_decisions_candidate_id_candidates", "candidates", ["id"])]
        assert {item["name"] for item in unique_constraints} == {
            "uq_candidate_decisions_candidate_id"
        }
        assert {item["name"] for item in check_constraints} == {
            "ck_candidate_decisions_status"
        }
        status_check = check_constraints[0]["sqltext"].casefold()
        assert "selected" in status_check
        assert "rejected" in status_check
        assert "reserve" not in status_check
    finally:
        engine.dispose()


def test_candidate_decisions_migration_downgrades_to_wave_one_and_upgrades_again(
    alembic_config: Config, isolated_database_url: str
) -> None:
    # Поломка: downgrade удаляет candidates либо повторный upgrade не восстанавливает журнал.
    command.upgrade(alembic_config, "20260802_02")

    engine = create_engine(isolated_database_url)
    try:
        assert "candidate_decisions" in inspect(engine).get_table_names()
    finally:
        engine.dispose()

    command.downgrade(alembic_config, "20260801_01")
    engine = create_engine(isolated_database_url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert "candidates" in tables
        assert "candidate_decisions" not in tables
    finally:
        engine.dispose()

    command.upgrade(alembic_config, "20260802_02")
    engine = create_engine(isolated_database_url)
    try:
        assert "candidate_decisions" in inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_content_migration_creates_complete_schema_and_downgrades_to_wave_two(
    alembic_config: Config, isolated_database_url: str
) -> None:
    # Поломка (gate 11/12): нет таблицы/поля или downgrade трогает Wave 2.
    command.upgrade(alembic_config, "20260808_03")
    engine = create_engine(isolated_database_url)
    expected_columns = {
        "content_quota_state": {"id", "fresh_credit", "reserve_credit", "updated_at"},
        "content_daily_usage": {"day", "analyses_started", "packages_created"},
        "content_attempts": {
            "id",
            "candidate_id",
            "attempt_no",
            "tier",
            "status",
            "source_url",
            "article_title",
            "article_text",
            "analysis",
            "failure_code",
            "retry_at",
            "started_at",
            "finished_at",
        },
        "content_packages": {
            "id",
            "attempt_id",
            "source_url",
            "context",
            "analysis",
            "post_text",
            "media_path",
            "media_mime",
            "media_source_type",
            "media_source_url",
            "review_required",
            "status",
            "media_deleted_at",
            "created_at",
            "updated_at",
        },
        "content_package_status_history": {
            "id",
            "package_id",
            "status",
            "reason",
            "created_at",
        },
    }
    try:
        inspector = inspect(engine)
        for table, columns in expected_columns.items():
            assert {item["name"] for item in inspector.get_columns(table)} == columns

        unique_names = {
            constraint["name"]
            for table in expected_columns
            for constraint in inspector.get_unique_constraints(table)
        }
        assert "uq_content_attempts_candidate_id_attempt_no" in unique_names
        assert "uq_content_packages_attempt_id" in unique_names
    finally:
        engine.dispose()

    command.downgrade(alembic_config, "20260802_02")
    engine = create_engine(isolated_database_url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert "candidates" in tables
        assert "candidate_decisions" in tables
        assert not set(expected_columns) & tables
    finally:
        engine.dispose()

    command.upgrade(alembic_config, "20260808_03")


def test_telegram_delivery_migration_has_exact_named_schema(
    alembic_config: Config, isolated_database_url: str
) -> None:
    # Поломка: delivery schema теряет nullable/timezone или named invariant.
    command.upgrade(alembic_config, "20260808_03")
    command.upgrade(alembic_config, "20260809_04")
    engine = create_engine(isolated_database_url)
    try:
        inspector = inspect(engine)
        assert {"telegram_deliveries", "telegram_delivery_attempts"} <= set(
            inspector.get_table_names()
        )
        delivery = {
            item["name"]: item for item in inspector.get_columns("telegram_deliveries")
        }
        attempts = {
            item["name"]: item
            for item in inspector.get_columns("telegram_delivery_attempts")
        }
        assert set(delivery) == {
            "id",
            "package_id",
            "status",
            "attempt_no",
            "message_id",
            "sending_started_at",
            "confirmed_at",
            "media_deleted_at",
            "failure_code",
            "failure_reason",
            "created_at",
            "updated_at",
        }
        assert set(attempts) == {
            "id",
            "delivery_id",
            "attempt_no",
            "outcome",
            "code",
            "reason",
            "started_at",
            "finished_at",
            "message_id",
        }
        assert all(
            delivery[name]["type"].timezone is True
            for name in (
                "sending_started_at",
                "confirmed_at",
                "media_deleted_at",
                "created_at",
                "updated_at",
            )
        )
        assert all(
            attempts[name]["type"].timezone is True
            for name in ("started_at", "finished_at")
        )
        assert {name for name, column in delivery.items() if column["nullable"]} == {
            "message_id",
            "confirmed_at",
            "media_deleted_at",
            "failure_code",
            "failure_reason",
        }
        assert {name for name, column in attempts.items() if column["nullable"]} == {
            "code",
            "reason",
            "message_id",
        }
        assert {
            item["name"]
            for item in inspector.get_unique_constraints("telegram_deliveries")
        } == {"uq_telegram_deliveries_package_id"}
        assert {
            item["name"]
            for item in inspector.get_unique_constraints("telegram_delivery_attempts")
        } == {"uq_telegram_delivery_attempts_delivery_id_attempt_no"}
        assert {
            item["name"] for item in inspector.get_foreign_keys("telegram_deliveries")
        } == {"fk_telegram_deliveries_package_id_content_packages"}
        assert {
            item["name"]
            for item in inspector.get_foreign_keys("telegram_delivery_attempts")
        } == {"fk_telegram_delivery_attempts_delivery_id_telegram_deliveries"}
        delivery_checks = inspector.get_check_constraints("telegram_deliveries")
        attempt_checks = inspector.get_check_constraints("telegram_delivery_attempts")
        assert {item["name"] for item in delivery_checks} == {
            "ck_telegram_deliveries_status"
        }
        assert {item["name"] for item in attempt_checks} == {
            "ck_telegram_delivery_attempts_outcome"
        }
        assert all(
            status in delivery_checks[0]["sqltext"]
            for status in ("sending", "retryable", "published", "failed", "uncertain")
        )
        assert all(
            status in attempt_checks[0]["sqltext"]
            for status in ("retryable", "published", "failed", "uncertain")
        )
    finally:
        engine.dispose()


def test_telegram_delivery_migration_downgrades_to_wave_three_and_upgrades_again(
    alembic_config: Config, isolated_database_url: str
) -> None:
    # Поломка: rollback оставляет Wave 4 или удаляет Wave 3.
    command.upgrade(alembic_config, "20260809_04")
    command.downgrade(alembic_config, "20260808_03")
    engine = create_engine(isolated_database_url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert "content_packages" in tables
        assert "content_package_status_history" in tables
        assert "telegram_deliveries" not in tables
        assert "telegram_delivery_attempts" not in tables
    finally:
        engine.dispose()

    command.upgrade(alembic_config, "20260809_04")
    engine = create_engine(isolated_database_url)
    try:
        assert {"telegram_deliveries", "telegram_delivery_attempts"} <= set(
            inspect(engine).get_table_names()
        )
    finally:
        engine.dispose()


def test_operation_runs_migration_has_exact_named_schema(
    alembic_config: Config, isolated_database_url: str
) -> None:
    # Поломка: Wave 5 таблица теряет column, timezone или именованный invariant.
    command.upgrade(alembic_config, "20260809_05")
    engine = create_engine(isolated_database_url)
    try:
        inspector = inspect(engine)
        assert "operation_runs" in inspector.get_table_names()
        columns = {
            item["name"]: item for item in inspector.get_columns("operation_runs")
        }
        assert set(columns) == {
            "id",
            "operation",
            "status",
            "outcome",
            "failure_code",
            "started_at",
            "finished_at",
        }
        assert columns["id"]["type"].__class__.__name__ == "BIGINT"
        assert columns["started_at"]["type"].timezone is True
        assert columns["finished_at"]["type"].timezone is True
        assert {name for name, column in columns.items() if column["nullable"]} == {
            "outcome",
            "failure_code",
            "finished_at",
        }
        checks = {
            item["name"]: item["sqltext"].casefold()
            for item in inspector.get_check_constraints("operation_runs")
        }
        assert set(checks) == {
            "ck_operation_runs_operation",
            "ck_operation_runs_status",
            "ck_operation_runs_terminal_fields",
        }
        assert all(
            code in checks["ck_operation_runs_operation"]
            for code in ("run_once", "publish_once")
        )
        assert all(
            code in checks["ck_operation_runs_status"]
            for code in ("running", "succeeded", "failed")
        )
        terminal = checks["ck_operation_runs_terminal_fields"]
        assert all(
            field in terminal for field in ("outcome", "failure_code", "finished_at")
        )
    finally:
        engine.dispose()


def test_operation_runs_upgrade_downgrade_reupgrade_preserves_wave_four_fixture(
    alembic_config: Config, isolated_database_url: str
) -> None:
    # Поломка: 04→05→04→05 удаляет package/delivery/attempt или message_id=6.
    command.upgrade(alembic_config, "20260809_04")
    engine = create_engine(isolated_database_url)
    now = datetime(2026, 8, 9, 9, tzinfo=UTC)
    try:
        with engine.begin() as connection:
            candidate_id = connection.execute(
                text(
                    "INSERT INTO candidates "
                    "(id,source_name,source_id,title,url,discovered_at,raw_payload) "
                    "VALUES (1,'hn','wave4','Wave 4','https://source.test/1',:now,'{}'::jsonb) "
                    "RETURNING id"
                ),
                {"now": now},
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO candidate_decisions "
                    "(id,candidate_id,status,reason,explanation,signals,policy_version,decided_at) "
                    "VALUES (1,:candidate_id,'selected','eligible_for_ai','safe','{}'::jsonb,'v1',:now)"
                ),
                {"candidate_id": candidate_id, "now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO content_attempts "
                    "(id,candidate_id,attempt_no,tier,status,source_url,article_title,article_text,"
                    "analysis,started_at,finished_at) VALUES "
                    "(1,:candidate_id,1,'fresh','packaged','https://source.test/1','title',"
                    "'article','analysis',:now,:now)"
                ),
                {"candidate_id": candidate_id, "now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO content_packages "
                    "(id,attempt_id,source_url,context,analysis,post_text,review_required,status,"
                    "created_at,updated_at) VALUES "
                    "(1,1,'https://source.test/1','context','analysis','post',true,'published',:now,:now)"
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO telegram_deliveries "
                    "(id,package_id,status,attempt_no,message_id,sending_started_at,confirmed_at,"
                    "media_deleted_at,created_at,updated_at) "
                    "VALUES (1,1,'published',1,6,:now,:now,:now,:now,:now)"
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO telegram_delivery_attempts "
                    "(id,delivery_id,attempt_no,outcome,started_at,finished_at,message_id) "
                    "VALUES (1,1,1,'published',:now,:now,6)"
                ),
                {"now": now},
            )
    finally:
        engine.dispose()

    def wave_four_fixture() -> tuple[object, ...]:
        current_engine = create_engine(isolated_database_url)
        try:
            with current_engine.connect() as connection:
                return connection.execute(
                    text(
                        "SELECT p.id,p.status,d.status,d.message_id,a.attempt_no,a.message_id "
                        "FROM content_packages p "
                        "JOIN telegram_deliveries d ON d.package_id=p.id "
                        "JOIN telegram_delivery_attempts a ON a.delivery_id=d.id "
                        "WHERE p.id=1"
                    )
                ).one()
        finally:
            current_engine.dispose()

    expected = (1, "published", "published", 6, 1, 6)
    assert wave_four_fixture() == expected
    command.upgrade(alembic_config, "20260809_05")
    assert wave_four_fixture() == expected
    command.downgrade(alembic_config, "20260809_04")
    assert wave_four_fixture() == expected
    engine = create_engine(isolated_database_url)
    try:
        assert "operation_runs" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()
    command.upgrade(alembic_config, "20260809_05")
    assert wave_four_fixture() == expected


def test_operation_runs_constraint_rejects_failure_code_for_other_operation(
    alembic_config: Config, isolated_database_url: str
) -> None:
    # Поломка: raw SQL caller сохраняет publish failure code для run-once.
    command.upgrade(alembic_config, "20260809_05")
    engine = create_engine(isolated_database_url)
    try:
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO operation_runs(operation,status,failure_code,started_at,finished_at) "
                        "VALUES ('run_once','failed','publish_once_failed',:now,:now)"
                    ),
                    {"now": datetime(2026, 8, 9, 9, tzinfo=UTC)},
                )
    finally:
        engine.dispose()


def test_wave_ten_head_has_complete_manual_journal_and_project_safe_versions(
    alembic_config: Config, isolated_database_url: str
) -> None:
    # Break caught: the final head omits polling metadata or permits cross-project lineage.
    command.upgrade(alembic_config, "20260905_18")
    engine = create_engine(isolated_database_url)
    try:
        inspector = inspect(engine)
        operation_columns = {
            column["name"]: column for column in inspector.get_columns("operation_runs")
        }
        assert {
            "mode",
            "actor",
            "codex_model",
            "codex_reasoning_effort",
            "materials_taken",
            "packages_created",
        } <= operation_columns.keys()
        assert operation_columns["materials_taken"]["nullable"] is False
        assert operation_columns["packages_created"]["nullable"] is False
        history_columns = {
            column["name"]: column
            for column in inspector.get_columns("content_package_status_history")
        }
        assert history_columns["reason"]["nullable"] is True
        package_foreign_keys = {
            item["name"]: item for item in inspector.get_foreign_keys("content_packages")
        }
        assert package_foreign_keys[
            "fk_content_packages_project_previous_package"
        ]["constrained_columns"] == ["project_id", "previous_package_id"]
        media_foreign_keys = {
            item["name"]: item
            for item in inspector.get_foreign_keys("content_package_media_versions")
        }
        assert media_foreign_keys[
            "fk_content_package_media_versions_project_package"
        ]["constrained_columns"] == ["project_id", "package_id"]
        media_indexes = {
            item["name"]: item
            for item in inspector.get_indexes("content_package_media_versions")
        }
        assert media_indexes[
            "ix_content_package_media_versions_project_package"
        ]["column_names"] == ["project_id", "package_id"]
        checks = {
            item["name"] for item in inspector.get_check_constraints("operation_runs")
        }
        assert {"ck_operation_runs_metadata", "ck_operation_runs_outcome"} <= checks
    finally:
        engine.dispose()

    command.downgrade(alembic_config, "20260817_15")
    engine = create_engine(isolated_database_url)
    try:
        assert "codex_model" not in {
            column["name"] for column in inspect(engine).get_columns("operation_runs")
        }
    finally:
        engine.dispose()


def test_wave_ten_downgrades_restore_exact_previous_terminal_constraints(
    alembic_config: Config, isolated_database_url: str
) -> None:
    command.upgrade(alembic_config, "20260905_18")
    expectations = [
        ("20260817_14", "retry_delivery_failed", "manual_search_failed"),
        ("20260817_13", "replace_media_failed", "retry_delivery_failed"),
        ("20260817_12", "return_to_analysis_failed", "regenerate_post_failed"),
        ("20260817_11", "load_more_failed", "retry_analysis_failed"),
        ("20260817_10", "publish_once_failed", "load_more_failed"),
    ]

    for revision, retained, removed in expectations:
        command.downgrade(alembic_config, revision)
        engine = create_engine(isolated_database_url)
        try:
            constraint = next(
                item["sqltext"]
                for item in inspect(engine).get_check_constraints("operation_runs")
                if item["name"] == "ck_operation_runs_terminal_fields"
            )
            assert retained in constraint
            assert removed not in constraint
        finally:
            engine.dispose()


def test_project_migration_scopes_existing_rows_and_generalises_connections(
    alembic_config: Config, isolated_database_url: str
) -> None:
    command.upgrade(alembic_config, "20260809_05")
    engine = create_engine(isolated_database_url)
    now = datetime(2026, 8, 12, 9, tzinfo=UTC)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO candidates "
                    "(id,source_name,source_id,title,url,discovered_at,raw_payload) "
                    "VALUES (1,'hn_algolia','legacy','Legacy','https://example.test/1',:now,'{}'::jsonb)"
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO operation_runs "
                    "(id,operation,status,outcome,started_at,finished_at) "
                    "VALUES (1,'run_once','succeeded','completed',:now,:now)"
                ),
                {"now": now},
            )
    finally:
        engine.dispose()

    command.upgrade(alembic_config, "20260812_06")
    engine = create_engine(isolated_database_url)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert {
            "content_projects",
            "source_connections",
            "content_formats",
            "calls_to_action",
            "channel_connections",
            "publication_routes",
            "deliveries",
            "delivery_attempts",
        } <= tables
        assert "telegram_deliveries" not in tables
        assert "telegram_delivery_attempts" not in tables
        for table in (
            "candidates",
            "candidate_decisions",
            "content_quota_state",
            "content_daily_usage",
            "content_attempts",
            "content_packages",
            "content_package_status_history",
            "deliveries",
            "delivery_attempts",
            "operation_runs",
        ):
            assert "project_id" in {
                column["name"] for column in inspector.get_columns(table)
            }
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT project_id FROM candidates WHERE id=1")
            ).scalar_one() == 1
            assert connection.execute(
                text("SELECT project_id FROM operation_runs WHERE id=1")
            ).scalar_one() == 1
            assert connection.execute(
                text("SELECT count(*) FROM content_projects")
            ).scalar_one() == 1
    finally:
        engine.dispose()

    command.downgrade(alembic_config, "20260809_05")
    engine = create_engine(isolated_database_url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert "telegram_deliveries" in tables
        assert "telegram_delivery_attempts" in tables
        assert "content_projects" not in tables
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT count(*) FROM candidates WHERE id=1")
            ).scalar_one() == 1
    finally:
        engine.dispose()


def test_production_invariants_migration_downgrades_and_upgrades_again(
    alembic_config: Config, isolated_database_url: str
) -> None:
    # Поломка final review: project_id default не снят или rollback неповторяем.
    command.upgrade(alembic_config, "20260905_18")
    engine = create_engine(isolated_database_url)
    try:
        inspector = inspect(engine)
        assert "project_id" in {column["name"] for column in inspector.get_columns("candidates")}
        assert next(
            column
            for column in inspector.get_columns("candidates")
            if column["name"] == "project_id"
        )["default"] is None
        active_index = next(
            index
            for index in inspector.get_indexes("operation_runs")
            if index["name"] == "uq_operation_runs_active_project_operation"
        )
        assert active_index["unique"] is True
    finally:
        engine.dispose()

    command.downgrade(alembic_config, "20260812_07")
    engine = create_engine(isolated_database_url)
    try:
        project_default = next(
            column
            for column in inspect(engine).get_columns("candidates")
            if column["name"] == "project_id"
        )["default"]
        assert project_default is not None and "1" in project_default
    finally:
        engine.dispose()

    command.upgrade(alembic_config, "20260905_18")
    engine = create_engine(isolated_database_url)
    try:
        project_default = next(
            column
            for column in inspect(engine).get_columns("candidates")
            if column["name"] == "project_id"
        )["default"]
        assert project_default is None
    finally:
        engine.dispose()


def test_project_migration_downgrade_reports_project_scoped_duplicates(
    alembic_config: Config, isolated_database_url: str
) -> None:
    # Поломка final review: rollback падает opaque unique violation вместо preflight.
    command.upgrade(alembic_config, "20260905_18")
    engine = create_engine(isolated_database_url)
    now = datetime(2026, 8, 13, 9, tzinfo=UTC)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """INSERT INTO content_projects
                    (id,name,topic,language,audience,timezone,configuration,created_at,updated_at)
                    VALUES (2,'Второй','Тема','ru','Аудитория','Europe/Moscow',
                            '{}'::jsonb,:now,:now)"""
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    """INSERT INTO candidates
                    (id,project_id,source_name,source_id,title,url,discovered_at,raw_payload)
                    VALUES
                    (1,1,'source','same','Первый','https://example.test/1',:now,'{}'),
                    (2,2,'source','same','Второй','https://example.test/2',:now,'{}')"""
                ),
                {"now": now},
            )
    finally:
        engine.dispose()

    with pytest.raises(
        ProgrammingError,
        match="Нельзя откатить 20260812_06.*candidates",
    ):
        command.downgrade(alembic_config, "20260809_05")


def test_codex_analysis_profile_migration_backfills_and_downgrades(
    alembic_config: Config, isolated_database_url: str
) -> None:
    command.upgrade(alembic_config, "20260817_09")
    engine = create_engine(isolated_database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE content_projects SET configuration="
                    "jsonb_build_object('analysis_timeout_seconds',600) WHERE id=1"
                )
            )
    finally:
        engine.dispose()
    command.upgrade(alembic_config, "20260817_10")
    engine = create_engine(isolated_database_url)
    try:
        with engine.connect() as connection:
            configuration = connection.execute(
                text("SELECT configuration FROM content_projects WHERE id=1")
            ).scalar_one()
        assert configuration["analysis_model"] == "gpt-5.6-luna"
        assert configuration["analysis_reasoning_effort"] == "high"
    finally:
        engine.dispose()

    command.downgrade(alembic_config, "20260817_09")
    engine = create_engine(isolated_database_url)
    try:
        with engine.connect() as connection:
            configuration = connection.execute(
                text("SELECT configuration FROM content_projects WHERE id=1")
            ).scalar_one()
        assert "analysis_model" not in configuration
        assert "analysis_reasoning_effort" not in configuration
    finally:
        engine.dispose()
