from __future__ import annotations

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect


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
    command.upgrade(alembic_config, "head")

    engine = create_engine(isolated_database_url)
    try:
        inspector = inspect(engine)
        columns = {column["name"]: column for column in inspector.get_columns("candidates")}
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

    command.upgrade(alembic_config, "head")
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
    command.upgrade(alembic_config, "head")

    engine = create_engine(isolated_database_url)
    try:
        inspector = inspect(engine)
        columns = {column["name"]: column for column in inspector.get_columns("candidate_decisions")}
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
        assert [(item["name"], item["referred_table"], item["referred_columns"]) for item in foreign_keys] == [
            ("fk_candidate_decisions_candidate_id_candidates", "candidates", ["id"])
        ]
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
    command.upgrade(alembic_config, "head")

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

    command.upgrade(alembic_config, "head")
    engine = create_engine(isolated_database_url)
    try:
        assert "candidate_decisions" in inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_content_migration_creates_complete_schema_and_downgrades_to_wave_two(
    alembic_config: Config, isolated_database_url: str
) -> None:
    # Поломка (gate 11/12): нет таблицы/поля или downgrade трогает Wave 2.
    command.upgrade(alembic_config, "head")
    engine = create_engine(isolated_database_url)
    expected_columns = {
        "content_quota_state": {"id", "fresh_credit", "reserve_credit", "updated_at"},
        "content_daily_usage": {"day", "analyses_started", "packages_created"},
        "content_attempts": {
            "id", "candidate_id", "attempt_no", "tier", "status", "source_url",
            "article_title", "article_text", "analysis", "failure_code", "retry_at",
            "started_at", "finished_at",
        },
        "content_packages": {
            "id", "attempt_id", "source_url", "context", "analysis", "post_text",
            "media_path", "media_mime", "media_source_type", "media_source_url",
            "review_required", "status", "media_deleted_at", "created_at", "updated_at",
        },
        "content_package_status_history": {
            "id", "package_id", "status", "reason", "created_at",
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

    command.upgrade(alembic_config, "head")


def test_telegram_delivery_migration_has_exact_named_schema(
    alembic_config: Config, isolated_database_url: str
) -> None:
    # Поломка: delivery schema теряет nullable/timezone или named invariant.
    command.upgrade(alembic_config, "20260808_03")
    command.upgrade(alembic_config, "head")
    engine = create_engine(isolated_database_url)
    try:
        inspector = inspect(engine)
        assert {"telegram_deliveries", "telegram_delivery_attempts"} <= set(
            inspector.get_table_names()
        )
        delivery = {item["name"]: item for item in inspector.get_columns("telegram_deliveries")}
        attempts = {
            item["name"]: item
            for item in inspector.get_columns("telegram_delivery_attempts")
        }
        assert set(delivery) == {
            "id", "package_id", "status", "attempt_no", "message_id",
            "sending_started_at", "confirmed_at", "media_deleted_at",
            "failure_code", "failure_reason", "created_at", "updated_at",
        }
        assert set(attempts) == {
            "id", "delivery_id", "attempt_no", "outcome", "code", "reason",
            "started_at", "finished_at", "message_id",
        }
        assert all(delivery[name]["type"].timezone is True for name in (
            "sending_started_at", "confirmed_at", "media_deleted_at", "created_at", "updated_at"
        ))
        assert all(attempts[name]["type"].timezone is True for name in ("started_at", "finished_at"))
        assert {name for name, column in delivery.items() if column["nullable"]} == {
            "message_id", "confirmed_at", "media_deleted_at", "failure_code", "failure_reason"
        }
        assert {name for name, column in attempts.items() if column["nullable"]} == {
            "code", "reason", "message_id"
        }
        assert {item["name"] for item in inspector.get_unique_constraints("telegram_deliveries")} == {
            "uq_telegram_deliveries_package_id"
        }
        assert {item["name"] for item in inspector.get_unique_constraints("telegram_delivery_attempts")} == {
            "uq_telegram_delivery_attempts_delivery_id_attempt_no"
        }
        assert {item["name"] for item in inspector.get_foreign_keys("telegram_deliveries")} == {
            "fk_telegram_deliveries_package_id_content_packages"
        }
        assert {item["name"] for item in inspector.get_foreign_keys("telegram_delivery_attempts")} == {
            "fk_telegram_delivery_attempts_delivery_id_telegram_deliveries"
        }
        delivery_checks = inspector.get_check_constraints("telegram_deliveries")
        attempt_checks = inspector.get_check_constraints("telegram_delivery_attempts")
        assert {item["name"] for item in delivery_checks} == {"ck_telegram_deliveries_status"}
        assert {item["name"] for item in attempt_checks} == {"ck_telegram_delivery_attempts_outcome"}
        assert all(status in delivery_checks[0]["sqltext"] for status in (
            "sending", "retryable", "published", "failed", "uncertain"
        ))
        assert all(status in attempt_checks[0]["sqltext"] for status in (
            "retryable", "published", "failed", "uncertain"
        ))
    finally:
        engine.dispose()


def test_telegram_delivery_migration_downgrades_to_wave_three_and_upgrades_again(
    alembic_config: Config, isolated_database_url: str
) -> None:
    # Поломка: rollback оставляет Wave 4 или удаляет Wave 3.
    command.upgrade(alembic_config, "head")
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

    command.upgrade(alembic_config, "head")
    engine = create_engine(isolated_database_url)
    try:
        assert {"telegram_deliveries", "telegram_delivery_attempts"} <= set(
            inspect(engine).get_table_names()
        )
    finally:
        engine.dispose()
