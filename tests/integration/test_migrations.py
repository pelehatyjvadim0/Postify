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
