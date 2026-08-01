from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from postify.domain.candidates.models import Candidate


pytestmark = pytest.mark.integration


def candidate(source_id: str, **overrides: object) -> Candidate:
    values: dict[str, object] = {
        "source_name": "hacker_news",
        "source_id": source_id,
        "title": "Практический материал",
        "url": f"https://example.test/{source_id}",
        "discovered_at": datetime(2026, 8, 1, 9, 30, tzinfo=UTC),
        "raw_payload": {"objectID": source_id},
    }
    values.update(overrides)
    return Candidate(**values)  # type: ignore[arg-type]


def test_engine_is_created_from_passed_settings(migrated_database_url: str) -> None:
    from postify.infrastructure.database.engine import create_engine_from_settings

    engine = create_engine_from_settings(SimpleNamespace(database_url=migrated_database_url))
    try:
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT 1").scalar_one() == 1
    finally:
        engine.dispose()


def test_save_new_creates_only_distinct_source_keys_and_persists_after_session_closes(
    migrated_database_url: str,
) -> None:
    from postify.infrastructure.database.models import CandidateModel
    from postify.infrastructure.repositories.sqlalchemy_candidates import (
        SqlAlchemyCandidateRepository,
    )

    engine = create_engine(migrated_database_url)
    session_factory = sessionmaker(engine)
    repository = SqlAlchemyCandidateRepository(session_factory)

    try:
        assert repository.save_new([candidate("1"), candidate("1"), candidate("2")]) == 2

        with session_factory() as second_session:
            saved = second_session.scalars(select(CandidateModel).order_by(CandidateModel.source_id)).all()

        assert [item.source_id for item in saved] == ["1", "2"]
    finally:
        engine.dispose()


def test_save_new_keeps_original_fields_when_source_key_already_exists(
    migrated_database_url: str,
) -> None:
    from postify.infrastructure.database.models import CandidateModel
    from postify.infrastructure.repositories.sqlalchemy_candidates import (
        SqlAlchemyCandidateRepository,
    )

    engine = create_engine(migrated_database_url)
    session_factory = sessionmaker(engine)
    repository = SqlAlchemyCandidateRepository(session_factory)
    original = candidate("1")
    replacement = candidate(
        "1",
        title="Новый заголовок",
        url="https://example.test/replacement",
        raw_payload={"objectID": "replacement"},
    )

    try:
        assert repository.save_new([original]) == 1
        assert repository.save_new([replacement]) == 0

        with session_factory() as session:
            saved = session.scalar(select(CandidateModel))

        assert saved is not None
        assert saved.title == "Практический материал"
        assert saved.url == "https://example.test/1"
        assert saved.raw_payload == {"objectID": "1"}
    finally:
        engine.dispose()


def test_concurrent_saves_of_one_source_key_create_exactly_one_row(
    migrated_database_url: str,
) -> None:
    from postify.infrastructure.database.models import CandidateModel
    from postify.infrastructure.repositories.sqlalchemy_candidates import (
        SqlAlchemyCandidateRepository,
    )

    engine = create_engine(migrated_database_url)
    session_factory = sessionmaker(engine)
    repository = SqlAlchemyCandidateRepository(session_factory)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            created_counts = list(executor.map(lambda _: repository.save_new([candidate("1")]), range(2)))

        with session_factory() as session:
            total = session.scalar(select(func.count()).select_from(CandidateModel))

        assert sum(created_counts) == 1
        assert total == 1
    finally:
        engine.dispose()


def test_save_new_rolls_back_serialization_error_and_accepts_the_next_batch(
    migrated_database_url: str,
) -> None:
    from postify.infrastructure.repositories.sqlalchemy_candidates import (
        SqlAlchemyCandidateRepository,
    )

    engine = create_engine(migrated_database_url)
    session_factory = sessionmaker(engine)
    repository = SqlAlchemyCandidateRepository(session_factory)
    invalid = candidate("invalid", raw_payload={"not_json": object()})

    try:
        with pytest.raises(TypeError, match="not JSON serializable"):
            repository.save_new([invalid])

        assert repository.save_new([candidate("valid")]) == 1
    finally:
        engine.dispose()
