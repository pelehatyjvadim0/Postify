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
