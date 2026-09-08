from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from postify.domain.candidates.models import Candidate
from postify.infrastructure.repositories.sqlalchemy_candidates import SqlAlchemyCandidateRepository
from postify.infrastructure.repositories.sqlalchemy_content import SqlAlchemyContentRepository

pytestmark = pytest.mark.integration
NOW = datetime(2026, 9, 5, tzinfo=UTC)


def _seed(engine, count: int) -> None:
    repository = SqlAlchemyCandidateRepository(sessionmaker(engine))
    assert repository.save_new([
        Candidate("telegram_group", f"group:{item}", f"Материал {item}", "", NOW, {}, source_text=f"Полный текст {item}")
        for item in range(count)
    ]) == count


def test_claim_uses_technical_batch_size_without_daily_quota(migrated_database_url: str) -> None:
    engine = create_engine(migrated_database_url)
    _seed(engine, 3)
    repository = SqlAlchemyContentRepository(sessionmaker(engine))
    try:
        first = repository.claim(now=NOW, batch_size=2)
        second = repository.claim(now=NOW, batch_size=2)
        assert [item.source_text for item in first] == ["Полный текст 0", "Полный текст 1"]
        assert [item.source_text for item in second] == ["Полный текст 2"]
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM content_attempts")).scalar_one() == 3
    finally:
        engine.dispose()


def test_concurrent_claims_take_each_imported_material_once(migrated_database_url: str) -> None:
    engine = create_engine(migrated_database_url)
    _seed(engine, 2)
    try:
        def claim() -> tuple[int, ...]:
            repository = SqlAlchemyContentRepository(sessionmaker(engine))
            return tuple(item.candidate_id for item in repository.claim(now=NOW, batch_size=2))
        with ThreadPoolExecutor(max_workers=2) as executor:
            claimed = tuple(executor.map(lambda _: claim(), range(2)))
        flattened = tuple(candidate_id for group in claimed for candidate_id in group)
        assert len(flattened) == 2
        assert len(set(flattened)) == 2
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM content_attempts WHERE status='processing'")).scalar_one() == 2
    finally:
        engine.dispose()
