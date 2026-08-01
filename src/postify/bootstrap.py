from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from time import monotonic, sleep

import httpx
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from postify.adapters.sources.hn_algolia import HnAlgoliaCandidateSource
from postify.application.ingestion.import_candidates import ImportCandidates
from postify.config import Settings
from postify.infrastructure.database.engine import create_engine_from_settings
from postify.infrastructure.repositories.sqlalchemy_candidates import SqlAlchemyCandidateRepository


class DatabaseUnavailableError(RuntimeError):
    """PostgreSQL не стал доступен до истечения заданного времени."""


@contextmanager
def open_importer(
    settings: Settings, *, transport: httpx.BaseTransport | None = None
) -> Iterator[ImportCandidates]:
    engine = create_engine_from_settings(settings)
    client: httpx.Client | None = None
    try:
        client = httpx.Client(timeout=httpx.Timeout(10.0), transport=transport)
        source = HnAlgoliaCandidateSource(
            client=client,
            url=settings.hn_algolia_url,
            query=settings.hn_query,
            tags=settings.hn_tags,
            hits=settings.hn_hits_per_page,
        )
        repository = SqlAlchemyCandidateRepository(sessionmaker(engine))
        yield ImportCandidates(source, repository)
    finally:
        if client is not None:
            client.close()
        engine.dispose()


def database_is_ready(settings: Settings) -> bool:
    engine = create_engine_from_settings(settings)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError:
        return False
    finally:
        engine.dispose()


def wait_for_database(settings: Settings) -> None:
    deadline = monotonic() + settings.database_readiness_timeout_seconds
    while not database_is_ready(settings):
        if monotonic() >= deadline:
            raise DatabaseUnavailableError("БД недоступна до истечения времени ожидания")
        sleep(0.1)


def migrations_at_head(settings: Settings) -> bool:
    project_root = Path(__file__).resolve().parents[2]
    alembic_config = Config(str(project_root / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(project_root / "migrations"))
    expected_heads = set(ScriptDirectory.from_config(alembic_config).get_heads())
    engine = create_engine_from_settings(settings)
    try:
        with engine.connect() as connection:
            current_heads = set(MigrationContext.configure(connection).get_current_heads())
        return current_heads == expected_heads
    finally:
        engine.dispose()


def candidate_count(settings: Settings) -> int:
    engine = create_engine_from_settings(settings)
    try:
        return SqlAlchemyCandidateRepository(sessionmaker(engine)).count()
    finally:
        engine.dispose()
