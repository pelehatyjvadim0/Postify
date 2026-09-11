from __future__ import annotations

from collections.abc import Iterator
import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text


def _schema_url(database_url: str, schema_name: str) -> str:
    # public в пути обязателен: расширение vector живёт там, а тип и операторы
    # pgvector видны только по search_path. Таблицы всё равно создаются в
    # первой схеме пути, то есть в изолированной.
    separator = "&" if "?" in database_url else "?"
    return f"{database_url}{separator}options=-csearch_path%3D{schema_name}%2Cpublic"


@pytest.fixture(scope="session")
def test_database_url() -> str:
    database_url = os.getenv("TEST_DATABASE_URL")
    if database_url is None:
        raise RuntimeError("Для integration-тестов требуется TEST_DATABASE_URL")

    production_url = os.getenv("DATABASE_URL")
    if database_url == production_url:
        raise RuntimeError("TEST_DATABASE_URL не может совпадать с DATABASE_URL")

    return database_url


@pytest.fixture
def isolated_database_url(test_database_url: str) -> Iterator[str]:
    schema_name = f"postify_test_{uuid4().hex}"
    admin_engine = create_engine(test_database_url)
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))

    try:
        yield _schema_url(test_database_url, schema_name)
    finally:
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
        admin_engine.dispose()


@pytest.fixture
def alembic_config(monkeypatch: pytest.MonkeyPatch, isolated_database_url: str) -> Config:
    monkeypatch.setenv("POSTIFY_ALEMBIC_DATABASE_URL", isolated_database_url)
    return Config("alembic.ini")


@pytest.fixture
def migrated_database_url(alembic_config: Config, isolated_database_url: str) -> Iterator[str]:
    command.upgrade(alembic_config, "head")
    yield isolated_database_url
